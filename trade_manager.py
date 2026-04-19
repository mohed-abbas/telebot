"""Trade manager — the brain of the signal execution pipeline.

Responsibilities:
  - Zone-based execution logic (market vs limit)
  - Stale signal detection (price already past TP1)
  - Position tracking and signal-to-position mapping
  - Trade management (modify SL, partial close, full close)
  - Daily limit enforcement
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

import db
from models import (
    AccountConfig,
    AccountSettings,
    Direction,
    GlobalConfig,
    SignalAction,
    SignalType,
)
from mt5_connector import MT5Connector, DryRunConnector, OrderType, OrderResult
from risk_calculator import (
    calculate_lot_size,
    calculate_sl_distance,
    calculate_sl_with_jitter,
    calculate_tp_with_jitter,
)

logger = logging.getLogger(__name__)


# ── Phase 6 staged-entry pure helpers (D-11..D-15) ───────────────────

class Band(NamedTuple):
    """One entry band for a correlated follow-up stage (stages 2..N).

    stage_number is 2..N because stage 1 is the text-only market fill and
    does not get a band.
    """
    stage_number: int
    low: float
    high: float


def compute_bands(
    zone_low: float,
    zone_high: float,
    max_stages: int,
    direction: str,
) -> list[Band]:
    """D-11/D-12: N-1 equal-width bands across (zone_low, zone_high).

    Stage 1 is the text-only market fill and does NOT get a band — bands
    are only emitted for stages 2..N.

    Invariants:
      - len(return) == max_stages - 1
      - bands[i].low == zone_low + i*width; bands[i].high == zone_low + (i+1)*width
      - bands are contiguous, non-overlapping, partition the zone exactly.
      - stage_number = i + 2

    Research Q5 RESOLVED: zone_low == zone_high is accepted; all N-1 stages
    are collapsed to point-bands, which fire together on arrival.

    Raises:
      ValueError if zone_low > zone_high (inverted zone).
    """
    if max_stages < 2:
        return []
    if zone_low > zone_high:
        raise ValueError(f"zone_low {zone_low} must be <= zone_high {zone_high}")
    n_bands = max_stages - 1
    if zone_low == zone_high:
        return [Band(stage_number=i + 2, low=zone_low, high=zone_low) for i in range(n_bands)]
    width = (zone_high - zone_low) / n_bands
    return [
        Band(stage_number=i + 2, low=zone_low + i * width, high=zone_low + (i + 1) * width)
        for i in range(n_bands)
    ]


def stage_is_in_zone_at_arrival(
    band: Band, current_bid: float, current_ask: float, direction: str,
) -> bool:
    """D-13: True if price has already crossed this band's trigger edge.

    BUY — long sequence, price moving DOWN into the zone. Trigger edge is
    band.high; in-zone when current_ask <= band.high.
    SELL — short sequence, price moving UP into the zone. Trigger edge is
    band.low; in-zone when current_bid >= band.low.

    Equality is inclusive; a point-band (band.low == band.high) fires when
    the relevant side of the spread equals that point.
    """
    if direction == "buy":
        return current_ask <= band.high
    return current_bid >= band.low


def stage_lot_size(snapshot: AccountSettings) -> float:
    """D-15: equal split across max_stages for both risk modes.

    For fixed_lot mode, snapshot.risk_value carries the target total lot size
    across all stages. For percent mode, snapshot.risk_value carries the total
    risk percent; per-stage slice is the equal share. Downstream sizing logic
    consumes this slice directly.
    """
    if snapshot.max_stages <= 0:
        return 0.0
    return snapshot.risk_value / snapshot.max_stages


def _pip_size_for_symbol(symbol: str) -> float:
    """Pip size by symbol — v1.1 only supports XAUUSD (1 pip = $0.01)."""
    if symbol.upper() == "XAUUSD":
        return 0.01
    logger.warning("Non-XAUUSD symbol %s — defaulting pip size to 0.0001", symbol)
    return 0.0001


# ── Effective-settings lookup (Phase 5, D-27) ───────────────────────

def _effective(tm, acct):
    """Return (risk_percent, max_lot_size, max_open_trades) for this account.

    Prefers SettingsStore.effective() when attached (DB source of truth, D-24).
    Falls back to AccountConfig when SettingsStore is None OR when the cache
    has no entry for this account (v1.0 unit tests, dry-run demos).

    When risk_mode == 'fixed_lot', risk_value carries the lot size — not a
    percent — so risk_percent still comes from AccountConfig in that mode.
    """
    store = getattr(tm, "settings_store", None)
    if store is not None:
        try:
            s = store.effective(acct.name)
            risk_percent = s.risk_value if s.risk_mode == "percent" else acct.risk_percent
            return risk_percent, s.max_lot_size, s.max_open_trades
        except KeyError:
            pass  # missing cache entry → fall through to JSON defaults
    return acct.risk_percent, acct.max_lot_size, acct.max_open_trades


# ── Zone logic (EXEC-01) ────────────────────────────────────────────

def is_price_in_buy_zone(current_price: float, zone_low: float, zone_high: float) -> bool:
    """BUY: execute market if price is at or below zone high (price is cheap enough)."""
    return current_price <= zone_high

def is_price_in_sell_zone(current_price: float, zone_low: float, zone_high: float) -> bool:
    """SELL: execute market if price is at or above zone low (price is high enough).
    Boundary inclusive — at exactly zone_low we still execute market."""
    return current_price >= zone_low

def determine_order_type(
    direction: Direction,
    current_price: float,
    zone_low: float,
    zone_high: float,
) -> tuple[bool, float]:
    """Determine market vs limit order and the limit price.
    Returns: (use_market: bool, limit_price: float)
    BUY zones:  price <= zone_high -> market, else buy_limit at zone_mid
    SELL zones: price >= zone_low  -> market, else sell_limit at zone_mid
    """
    zone_mid = (zone_low + zone_high) / 2
    if direction == Direction.SELL:
        if is_price_in_sell_zone(current_price, zone_low, zone_high):
            return True, 0.0
        else:
            return False, zone_mid
    else:  # BUY
        if is_price_in_buy_zone(current_price, zone_low, zone_high):
            return True, 0.0
        else:
            return False, zone_mid


# ── SL/TP validation (EXEC-03) ──────────────────────────────────────

def validate_sl_for_direction(direction: str, open_price: float, new_sl: float) -> bool:
    """Validate that SL makes sense for position direction.
    BUY: SL must be below open_price (we lose if price drops).
    SELL: SL must be above open_price (we lose if price rises).
    """
    if new_sl <= 0:
        return False
    if direction == "buy":
        return new_sl < open_price
    elif direction == "sell":
        return new_sl > open_price
    return False

def validate_tp_for_direction(direction: str, open_price: float, new_tp: float) -> bool:
    """Validate that TP makes sense for position direction.
    BUY: TP must be above open_price (we profit if price rises).
    SELL: TP must be below open_price (we profit if price drops).
    """
    if new_tp <= 0:
        return False
    if direction == "buy":
        return new_tp > open_price
    elif direction == "sell":
        return new_tp < open_price
    return False


class TradeManager:
    def __init__(
        self,
        connectors: dict[str, MT5Connector],
        accounts: list[AccountConfig],
        global_config: GlobalConfig,
    ):
        self.connectors = connectors  # account_name → connector
        self.accounts = {a.name: a for a in accounts}
        self.cfg = global_config
        # Phase 5 (D-27): optional SettingsStore; bot.py attaches after construction.
        # Falls back to AccountConfig values when None (v1.0 unit tests, dry-run demos).
        self.settings_store = None  # type: ignore[assignment]

    async def handle_signal(self, signal: SignalAction) -> list[dict]:
        """Process a parsed signal. Returns list of execution results for notification."""
        if signal.type == SignalType.OPEN_TEXT_ONLY:
            return await self._handle_text_only_open(signal)
        if signal.type == SignalType.OPEN:
            # Phase 6 D-05 — try to correlate to a recent orphan first.
            paired_signal_id = None
            correlator = getattr(self, "correlator", None)
            if correlator and signal.direction is not None:
                paired_signal_id = await correlator.pair_followup(
                    symbol=signal.symbol, direction=signal.direction.value,
                )
            if paired_signal_id is not None:
                return await self._handle_correlated_followup(signal, paired_signal_id)
            # v1.0 fallback — standalone OPEN, unchanged.
            return await self._handle_open(signal)
        elif signal.type == SignalType.CLOSE:
            return await self._handle_close(signal)
        elif signal.type == SignalType.CLOSE_PARTIAL:
            return await self._handle_close_partial(signal)
        elif signal.type == SignalType.MODIFY_SL:
            return await self._handle_modify_sl(signal)
        elif signal.type == SignalType.MODIFY_TP:
            return await self._handle_modify_tp(signal)
        return []

    # ── Phase 6: TEXT-ONLY OPEN (STAGE-02) ───────────────────────────

    async def _handle_text_only_open(self, signal: SignalAction) -> list[dict]:
        """OPEN_TEXT_ONLY: fire stage 1 at market with default SL; register orphan.

        Per account:
          1. Log the signal row (signal_id).
          2. Register the orphan with the correlator so a follow-up can pair.
          3. Snapshot AccountSettings (D-30) and compute default_sl_price.
          4. Insert a staged_entries row for stage 1 (status='awaiting_zone').
          5. Call _execute_open_on_account(staged=True, stage_number=1, stage_row_id=...).
        """
        results: list[dict] = []

        signal_id = await db.log_signal(
            raw_text=signal.raw_text,
            signal_type="open_text_only",
            action_taken="staged",
            symbol=signal.symbol,
            direction=signal.direction.value if signal.direction else "",
        )

        correlator = getattr(self, "correlator", None)
        if correlator and signal.direction is not None:
            await correlator.register_orphan(
                signal_id=signal_id,
                symbol=signal.symbol,
                direction=signal.direction.value,
            )

        store = getattr(self, "settings_store", None)
        pip_size = _pip_size_for_symbol(signal.symbol)

        for acct_name, connector in self.connectors.items():
            acct = self.accounts.get(acct_name)
            if not acct or not acct.enabled:
                continue
            if not connector.connected:
                results.append({"account": acct_name, "status": "skipped", "reason": "disconnected"})
                continue

            try:
                snapshot = store.snapshot(acct_name) if store else None
            except KeyError:
                snapshot = None

            price_data = await connector.get_price(signal.symbol)
            if price_data is None:
                results.append({"account": acct_name, "status": "failed", "reason": "no price for default SL"})
                continue
            bid, ask = price_data
            default_sl_pips = snapshot.default_sl_pips if snapshot else 100
            if signal.direction == Direction.BUY:
                sl_price = ask - (default_sl_pips * pip_size)
            else:
                sl_price = bid + (default_sl_pips * pip_size)

            comment = f"telebot-{signal_id}-s1"

            stage_row = {
                "signal_id": signal_id,
                "stage_number": 1,
                "account_name": acct_name,
                "symbol": signal.symbol,
                "direction": signal.direction.value,
                "zone_low": 0.0,
                "zone_high": 0.0,
                "band_low": 0.0,
                "band_high": 0.0,
                "target_lot": stage_lot_size(snapshot) if snapshot else 0.0,
                "snapshot_settings": asdict(snapshot) if snapshot else {},
                "mt5_comment": comment,
                "status": "awaiting_zone",
            }
            try:
                [stage_id] = await db.create_staged_entries([stage_row])
            except Exception as exc:  # UNIQUE(mt5_comment) violation — idempotency
                logger.warning("%s: stage 1 insert failed (idempotency?): %s", acct_name, exc)
                results.append({"account": acct_name, "status": "skipped", "reason": "duplicate"})
                continue

            synth = SignalAction(
                type=SignalType.OPEN_TEXT_ONLY,
                symbol=signal.symbol,
                raw_text=signal.raw_text,
                direction=signal.direction,
                entry_zone=None,
                sl=sl_price,
                tps=[],
                target_tp=None,
            )
            result = await self._execute_open_on_account(
                synth, signal_id, acct, connector,
                staged=True, stage_number=1, stage_row_id=stage_id, snapshot=snapshot,
            )
            if result.get("status") == "failed":
                await db.update_stage_status(
                    stage_id, "failed",
                    cancelled_reason=result.get("reason", "unknown"),
                )
            results.append(result)

        return results

    # ── Phase 6: CORRELATED FOLLOW-UP (STAGE-04) ──────────────────────

    async def _handle_correlated_followup(
        self, signal: SignalAction, paired_signal_id: int,
    ) -> list[dict]:
        """Follow-up OPEN paired with a text-only orphan.

        Per account:
          1. Snapshot AccountSettings (D-30).
          2. Compute N-1 equal bands across (zone_low, zone_high) (D-11/D-12).
          3. Insert all bands as staged_entries rows (status='awaiting_zone').
          4. Fire bands in-zone-at-arrival (D-13) immediately at market.
          5. Remaining armed bands stay awaiting_zone — Plan 04's _zone_watch_loop.

        Failure isolation (D-17): one band's broker-reject does not abort the rest.
        """
        results: list[dict] = []
        if signal.entry_zone is None or signal.direction is None:
            logger.warning("correlated follow-up missing entry_zone/direction — ignoring")
            return results

        store = getattr(self, "settings_store", None)

        for acct_name, connector in self.connectors.items():
            acct = self.accounts.get(acct_name)
            if not acct or not acct.enabled:
                continue
            if not connector.connected:
                results.append({"account": acct_name, "status": "skipped", "reason": "disconnected"})
                continue

            try:
                snapshot = store.snapshot(acct_name) if store else None
            except KeyError:
                snapshot = None
            max_stages = snapshot.max_stages if snapshot else 1
            bands = compute_bands(
                signal.entry_zone[0], signal.entry_zone[1],
                max_stages, signal.direction.value,
            )
            if not bands:
                results.append({"account": acct_name, "status": "no_bands", "reason": "max_stages=1"})
                continue

            rows = [
                {
                    "signal_id": paired_signal_id,
                    "stage_number": b.stage_number,
                    "account_name": acct_name,
                    "symbol": signal.symbol,
                    "direction": signal.direction.value,
                    "zone_low": signal.entry_zone[0],
                    "zone_high": signal.entry_zone[1],
                    "band_low": b.low,
                    "band_high": b.high,
                    "target_lot": stage_lot_size(snapshot) if snapshot else 0.0,
                    "snapshot_settings": asdict(snapshot) if snapshot else {},
                    "mt5_comment": f"telebot-{paired_signal_id}-s{b.stage_number}",
                    "status": "awaiting_zone",
                }
                for b in bands
            ]
            stage_ids = await db.create_staged_entries(rows)

            price_data = await connector.get_price(signal.symbol)
            if price_data is None:
                results.append({"account": acct_name, "status": "staged", "reason": "no_price_yet", "stages": len(rows)})
                continue
            bid, ask = price_data

            fired_count = 0
            for band, stage_id in zip(bands, stage_ids):
                if not stage_is_in_zone_at_arrival(band, bid, ask, signal.direction.value):
                    continue  # armed — Plan 04 will fire later
                synth = SignalAction(
                    type=SignalType.OPEN,
                    symbol=signal.symbol,
                    raw_text=signal.raw_text,
                    direction=signal.direction,
                    entry_zone=(band.low, band.high),
                    sl=signal.sl,
                    tps=list(signal.tps) if signal.tps else [],
                    target_tp=signal.target_tp,
                )
                result = await self._execute_open_on_account(
                    synth, paired_signal_id, acct, connector,
                    staged=True, stage_number=band.stage_number,
                    stage_row_id=stage_id, snapshot=snapshot,
                )
                if result.get("status") == "failed":
                    await db.update_stage_status(
                        stage_id, "failed",
                        cancelled_reason=result.get("reason", "broker_reject"),
                    )
                if result.get("status") in ("executed", "filled"):
                    fired_count += 1
                results.append(result)

            results.append({
                "account": acct_name, "status": "staged",
                "fired_at_arrival": fired_count,
                "armed": len(bands) - fired_count,
                "total": len(bands),
            })

        return results

    # ── OPEN ────────────────────────────────────────────────────────────

    async def _handle_open(self, signal: SignalAction) -> list[dict]:
        """Handle a new trade signal with zone-based execution."""
        results = []

        # Log the signal
        signal_id = await db.log_signal(
            raw_text=signal.raw_text,
            signal_type="open",
            action_taken="processing",
            symbol=signal.symbol,
            direction=signal.direction.value if signal.direction else "",
            entry_zone_low=signal.entry_zone[0] if signal.entry_zone else 0,
            entry_zone_high=signal.entry_zone[1] if signal.entry_zone else 0,
            sl=signal.sl or 0,
            tp=signal.target_tp or 0,
        )

        for acct_name, connector in self.connectors.items():
            acct = self.accounts.get(acct_name)
            if not acct or not acct.enabled:
                continue
            if not connector.connected:
                results.append({"account": acct_name, "status": "skipped", "reason": "disconnected"})
                continue

            result = await self._execute_open_on_account(signal, signal_id, acct, connector)
            results.append(result)

        return results

    async def _execute_open_on_account(
        self,
        signal: SignalAction,
        signal_id: int,
        acct: AccountConfig,
        connector: MT5Connector,
        *,
        staged: bool = False,
        stage_number: int = 1,
        stage_row_id: int | None = None,
        snapshot: "AccountSettings | None" = None,  # type: ignore[name-defined]
    ) -> dict:
        """Execute an open signal on a single account with all checks.

        Phase 6 additions (all keyword-only; defaults preserve v1.0 behavior):
          staged:       True when called from a Phase 6 staged dispatcher
                        (_handle_text_only_open or _handle_correlated_followup).
                        False for v1.0 _handle_open. Gates the D-18/D-19/D-23/D-24/D-25
                        staged-only behaviors so v1.0 callers stay on the literal
                        comment="telebot" + unconditional trades_count increment path.
          stage_number: 1 for text-only stage-1; 2..N for sibling stages
          stage_row_id: staged_entries.id — persisted on fill (D-38)
          snapshot:     frozen AccountSettings for per-stage D-30 snapshot; falls back
                        to SettingsStore.effective() via _effective() helper when None
        """
        name = acct.name
        # Phase 6 — stage_number > 1 on a staged call means stages 2..N of a
        # correlated sequence; the first fill already burned the daily-trades slot (D-18).
        is_sibling_stage = staged and stage_number > 1

        # ── Check daily limits ──────────────────────────────────────────
        # D-18: sibling stages (2..N) of a signal whose stage 1 already fired
        # do NOT re-check the trade-count budget — 1 signal = 1 slot.
        if not is_sibling_stage:
            trade_count = await db.get_daily_stat(name, "trades_count")
            if trade_count >= self.cfg.max_daily_trades_per_account:
                reason = f"Daily trade limit ({self.cfg.max_daily_trades_per_account}) reached"
                logger.warning("%s: %s", name, reason)
                return {"account": name, "status": "skipped", "reason": reason}

        msg_count = await db.get_daily_stat(name, "server_messages")
        if msg_count >= self.cfg.max_daily_server_messages:
            reason = f"Daily server message limit ({self.cfg.max_daily_server_messages}) reached"
            logger.warning("%s: %s", name, reason)
            return {"account": name, "status": "skipped", "reason": reason}

        # ── Check max open trades (Phase 5: via SettingsStore when attached) ─
        # D-19: for staged submissions, over-cap stages are marked 'capped' (not skipped)
        # so they show correctly on the /staged panel and don't resurrect on reconnect.
        positions = await connector.get_positions(signal.symbol)
        _, _, max_open = _effective(self, acct)
        if len(positions) >= max_open:
            if staged:
                # D-19 staged path — mark the row capped; never submit.
                if stage_row_id is not None:
                    await db.update_stage_status(
                        stage_row_id, "capped",
                        cancelled_reason=f"max_open_trades={max_open}",
                    )
                return {
                    "account": name, "status": "capped",
                    "reason": f"max_open_trades={max_open}",
                }
            reason = f"Max open trades ({max_open}) reached for {signal.symbol}"
            return {"account": name, "status": "skipped", "reason": reason}

        # ── Check duplicate (same direction already open) ───────────────
        # D-23 bypass: sibling stages of the same signal_id match the
        # 'telebot-{signal_id}-s*' comment prefix and skip the block.
        sibling_prefix = f"telebot-{signal_id}-s" if staged else None
        for pos in positions:
            if pos.direction == signal.direction.value:
                if sibling_prefix is not None and getattr(pos, "comment", "").startswith(sibling_prefix):
                    continue  # D-23 — sibling stage, allow
                reason = f"Already have a {signal.direction.value} position open on {signal.symbol}"
                return {"account": name, "status": "skipped", "reason": reason}

        # ── Feed simulated price for dry-run connectors ────────────────
        if isinstance(connector, DryRunConnector) and signal.entry_zone:
            zone_mid = (signal.entry_zone[0] + signal.entry_zone[1]) / 2
            spread = zone_mid * 0.0001  # ~1 pip spread
            connector.set_simulated_price(signal.symbol, zone_mid - spread / 2, zone_mid + spread / 2)

        # ── Get current price ───────────────────────────────────────────
        price_data = await connector.get_price(signal.symbol)
        if price_data is None:
            return {"account": name, "status": "failed", "reason": "Cannot get current price"}
        bid, ask = price_data

        # ── Stale signal check ──────────────────────────────────────────
        current_price = bid if signal.direction == Direction.SELL else ask
        stale_reason = self._check_stale(signal, current_price)
        if stale_reason:
            logger.info("%s: Stale signal — %s", name, stale_reason)
            return {"account": name, "status": "skipped", "reason": stale_reason}

        # ── Zone check → market or limit ────────────────────────────────
        # Phase 6 text-only path (entry_zone=None) always fires at market.
        if signal.entry_zone is None:
            use_market, limit_price = True, 0.0
        else:
            zone_low, zone_high = signal.entry_zone
            use_market, limit_price = self._determine_order_type(
                signal.direction, current_price, zone_low, zone_high,
            )

        # ── Calculate lot size ──────────────────────────────────────────
        acct_info = await connector.get_account_info()
        if acct_info is None:
            return {"account": name, "status": "failed", "reason": "Cannot get account info"}

        entry_for_calc = current_price if use_market else limit_price
        sl_distance = calculate_sl_distance(entry_for_calc, signal.sl)
        # Phase 5: effective risk/lot caps come from SettingsStore when attached.
        risk_pct, max_lot, _ = _effective(self, acct)
        lot_size = calculate_lot_size(
            account_balance=acct_info.balance,
            risk_percent=risk_pct,
            sl_distance=sl_distance,
            max_lot_size=max_lot,
            jitter_percent=self.cfg.lot_jitter_percent,
            symbol=signal.symbol,
        )

        if lot_size <= 0:
            return {"account": name, "status": "failed", "reason": "Calculated lot size is 0"}

        # ── Apply SL/TP jitter ──────────────────────────────────────────
        jittered_sl = calculate_sl_with_jitter(
            signal.sl, self.cfg.sl_tp_jitter_points, signal.direction,
        )
        jittered_tp = signal.target_tp
        if jittered_tp:
            jittered_tp = calculate_tp_with_jitter(
                jittered_tp, self.cfg.sl_tp_jitter_points, signal.direction,
            )

        # ── D-08: sl=0.0 is never acceptable ────────────────────────────
        # Applies to all paths; text-only is the likeliest source of this footgun
        # (default_sl_pips mis-computed or yielding a non-positive sl price).
        if jittered_sl is None or jittered_sl <= 0.0:
            reason = "Refusing to submit sl=0.0 — default_sl_pips must yield non-zero SL (D-08)"
            logger.error("%s: %s", name, reason)
            return {"account": name, "status": "failed", "reason": reason}

        # ── EXEC-02: Stale re-check immediately before order ─────────
        # Skip for text-only (no TPs) and follow-up stages where TPs are carried
        # but the correlated-followup dispatcher has already decided in-zone.
        if signal.tps:
            price_data_recheck = await connector.get_price(signal.symbol)
            if price_data_recheck is None:
                return {"account": name, "status": "failed", "reason": "Cannot get price for stale re-check"}
            bid_recheck, ask_recheck = price_data_recheck
            current_recheck = bid_recheck if signal.direction == Direction.SELL else ask_recheck
            stale_recheck = self._check_stale(signal, current_recheck)
            if stale_recheck:
                logger.info("%s: Stale on re-check — %s", name, stale_recheck)
                return {"account": name, "status": "skipped", "reason": f"Stale (re-check): {stale_recheck}"}

        # ── D-25 idempotency probe (staged path only) ───────────────────
        # Before submit, check if this stage already exists (DB status='filled')
        # or if MT5 already has a position with our exact comment (prior submit
        # that we lost track of due to crash/disconnect). In either case, skip
        # the resubmit.
        target_comment = f"telebot-{signal_id}-s{stage_number}" if staged else "telebot"
        if staged:
            existing = await db.get_stage_by_comment(target_comment)
            if existing and existing.get("status") == "filled":
                logger.info(
                    "%s: stage already filled (idempotency hit) signal_id=%d stage=%d",
                    name, signal_id, stage_number,
                )
                return {"account": name, "status": "skipped", "reason": "already_filled"}
            for p in positions:
                if getattr(p, "comment", "") == target_comment:
                    if stage_row_id is not None:
                        await db.update_stage_status(stage_row_id, "filled", mt5_ticket=p.ticket)
                    logger.info(
                        "%s: idempotency match — marked stage filled without resubmit ticket=%d",
                        name, p.ticket,
                    )
                    return {
                        "account": name, "status": "filled",
                        "ticket": p.ticket, "idempotent": True,
                    }

        # ── Execute ─────────────────────────────────────────────────────
        if use_market:
            order_type = (
                OrderType.MARKET_BUY if signal.direction == Direction.BUY
                else OrderType.MARKET_SELL
            )
            result = await connector.open_order(
                symbol=signal.symbol,
                order_type=order_type,
                volume=lot_size,
                sl=jittered_sl,
                tp=jittered_tp or 0.0,
                comment=target_comment,
            )
        else:
            order_type = (
                OrderType.BUY_LIMIT if signal.direction == Direction.BUY
                else OrderType.SELL_LIMIT
            )
            result = await connector.open_order(
                symbol=signal.symbol,
                order_type=order_type,
                volume=lot_size,
                price=limit_price,
                sl=jittered_sl,
                tp=jittered_tp or 0.0,
                comment=target_comment,
            )

        await db.increment_daily_stat(name, "server_messages")

        if result.success:
            # D-18 — 1 signal = 1 daily slot. For staged path, only increment
            # trades_count on the first successful fill of this signal_id on this
            # account (today). Unstaged v1.0 path keeps unconditional increment.
            if staged:
                first_fill = await db.mark_signal_counted_today(signal_id, name)
                if first_fill:
                    await db.increment_daily_stat(name, "trades_count")
            else:
                await db.increment_daily_stat(name, "trades_count")
            # Populate the staged_entries row with the fill ticket (D-38).
            if stage_row_id is not None:
                await db.update_stage_status(stage_row_id, "filled", mt5_ticket=result.ticket)
            await db.log_trade(
                signal_id=signal_id,
                account_name=name,
                symbol=signal.symbol,
                direction=signal.direction.value,
                entry_price=result.price,
                sl=jittered_sl,
                tp=jittered_tp or 0.0,
                lot_size=lot_size,
                ticket=result.ticket,
                status="opened" if use_market else "pending",
                raw_signal=signal.raw_text,
            )

            # Track limit order expiry
            if not use_market:
                expires_at = datetime.now(timezone.utc) + timedelta(minutes=self.cfg.limit_order_expiry_minutes)
                await db.log_pending_order(
                    signal_id=signal_id,
                    account_name=name,
                    ticket=result.ticket,
                    symbol=signal.symbol,
                    order_type=order_type.value,
                    volume=lot_size,
                    price=limit_price,
                    sl=jittered_sl,
                    tp=jittered_tp or 0.0,
                    expires_at=expires_at,
                )

            return {
                "account": name,
                "status": "executed" if use_market else "limit_placed",
                "ticket": result.ticket,
                "price": result.price if use_market else limit_price,
                "lot_size": lot_size,
                "sl": jittered_sl,
                "tp": jittered_tp or 0.0,
                "order_type": "market" if use_market else "limit",
            }
        else:
            await db.log_trade(
                signal_id=signal_id,
                account_name=name,
                symbol=signal.symbol,
                direction=signal.direction.value,
                entry_price=0,
                sl=jittered_sl,
                tp=jittered_tp or 0.0,
                lot_size=lot_size,
                ticket=0,
                status="failed",
                raw_signal=signal.raw_text,
            )
            return {"account": name, "status": "failed", "reason": result.error}

    def _check_stale(self, signal: SignalAction, current_price: float) -> str | None:
        """Check if the signal is stale (price already past TPs)."""
        if not signal.tps:
            return None

        numeric_tps = [tp for tp in signal.tps if isinstance(tp, (int, float))]
        if not numeric_tps:
            return None

        tp1 = numeric_tps[0]

        if signal.direction == Direction.SELL:
            # For SELL, price should be above TP1 (we're selling high, TP is below)
            if current_price <= tp1:
                return f"Price ({current_price:.2f}) already at/below TP1 ({tp1:.2f})"
        elif signal.direction == Direction.BUY:
            # For BUY, price should be below TP1 (we're buying low, TP is above)
            if current_price >= tp1:
                return f"Price ({current_price:.2f}) already at/above TP1 ({tp1:.2f})"

        return None

    def _determine_order_type(
        self,
        direction: Direction,
        current_price: float,
        zone_low: float,
        zone_high: float,
    ) -> tuple[bool, float]:
        """Determine market vs limit order. Delegates to module-level function."""
        return determine_order_type(direction, current_price, zone_low, zone_high)

    # ── CLOSE ───────────────────────────────────────────────────────────

    async def _handle_close(self, signal: SignalAction) -> list[dict]:
        results = []
        await db.log_signal(
            raw_text=signal.raw_text, signal_type="close",
            action_taken="processing", symbol=signal.symbol,
        )

        for acct_name, connector in self.connectors.items():
            acct = self.accounts.get(acct_name)
            if not acct or not acct.enabled or not connector.connected:
                continue

            positions = await connector.get_positions(signal.symbol)
            for pos in positions:
                result = await connector.close_position(pos.ticket)
                await db.increment_daily_stat(acct_name, "server_messages")
                if result.success:
                    await db.update_trade_close(pos.ticket, acct_name, pos.profit, result.price)
                    results.append({
                        "account": acct_name, "status": "closed",
                        "ticket": pos.ticket, "pnl": pos.profit,
                    })
                else:
                    results.append({
                        "account": acct_name, "status": "failed",
                        "ticket": pos.ticket, "reason": result.error,
                    })
        return results

    # ── CLOSE PARTIAL ───────────────────────────────────────────────────

    async def _handle_close_partial(self, signal: SignalAction) -> list[dict]:
        results = []
        close_fraction = (signal.close_percent or 50.0) / 100.0

        await db.log_signal(
            raw_text=signal.raw_text, signal_type="close_partial",
            action_taken="processing", symbol=signal.symbol,
            details=f"close {signal.close_percent}%",
        )

        for acct_name, connector in self.connectors.items():
            acct = self.accounts.get(acct_name)
            if not acct or not acct.enabled or not connector.connected:
                continue

            positions = await connector.get_positions(signal.symbol)
            for pos in positions:
                close_vol = round(pos.volume * close_fraction, 2)
                close_vol = max(close_vol, 0.01)
                if close_vol >= pos.volume:
                    close_vol = pos.volume  # full close if fraction rounds up

                result = await connector.close_position(pos.ticket, volume=close_vol)
                await db.increment_daily_stat(acct_name, "server_messages")
                if result.success:
                    results.append({
                        "account": acct_name, "status": "partial_closed",
                        "ticket": pos.ticket, "closed_volume": close_vol,
                    })
                else:
                    results.append({
                        "account": acct_name, "status": "failed",
                        "ticket": pos.ticket, "reason": result.error,
                    })
        return results

    # ── MODIFY SL ───────────────────────────────────────────────────────

    async def _handle_modify_sl(self, signal: SignalAction) -> list[dict]:
        results = []
        await db.log_signal(
            raw_text=signal.raw_text, signal_type="modify_sl",
            action_taken="processing", symbol=signal.symbol,
            details=f"new_sl={signal.new_sl}",
        )

        for acct_name, connector in self.connectors.items():
            acct = self.accounts.get(acct_name)
            if not acct or not acct.enabled or not connector.connected:
                continue

            positions = await connector.get_positions(signal.symbol)
            for pos in positions:
                new_sl = signal.new_sl
                if new_sl == 0.0:
                    # Breakeven: set SL to entry price
                    new_sl = pos.open_price

                # EXEC-03: Validate SL direction before sending to MT5
                if new_sl != pos.open_price and not validate_sl_for_direction(pos.direction, pos.open_price, new_sl):
                    results.append({
                        "account": acct_name, "status": "skipped",
                        "ticket": pos.ticket,
                        "reason": f"Invalid SL {new_sl:.2f} for {pos.direction} position (open={pos.open_price:.2f})",
                    })
                    continue

                result = await connector.modify_position(pos.ticket, sl=new_sl)
                await db.increment_daily_stat(acct_name, "server_messages")
                if result.success:
                    results.append({
                        "account": acct_name, "status": "sl_modified",
                        "ticket": pos.ticket, "new_sl": new_sl,
                    })
                else:
                    results.append({
                        "account": acct_name, "status": "failed",
                        "ticket": pos.ticket, "reason": result.error,
                    })
        return results

    # ── MODIFY TP ───────────────────────────────────────────────────────

    async def _handle_modify_tp(self, signal: SignalAction) -> list[dict]:
        results = []
        await db.log_signal(
            raw_text=signal.raw_text, signal_type="modify_tp",
            action_taken="processing", symbol=signal.symbol,
            details=f"new_tp={signal.new_tp}",
        )

        for acct_name, connector in self.connectors.items():
            acct = self.accounts.get(acct_name)
            if not acct or not acct.enabled or not connector.connected:
                continue

            positions = await connector.get_positions(signal.symbol)
            for pos in positions:
                # EXEC-03: Validate TP direction before sending to MT5
                if not validate_tp_for_direction(pos.direction, pos.open_price, signal.new_tp):
                    results.append({
                        "account": acct_name, "status": "skipped",
                        "ticket": pos.ticket,
                        "reason": f"Invalid TP {signal.new_tp:.2f} for {pos.direction} position (open={pos.open_price:.2f})",
                    })
                    continue

                result = await connector.modify_position(pos.ticket, tp=signal.new_tp)
                await db.increment_daily_stat(acct_name, "server_messages")
                if result.success:
                    results.append({
                        "account": acct_name, "status": "tp_modified",
                        "ticket": pos.ticket, "new_tp": signal.new_tp,
                    })
                else:
                    results.append({
                        "account": acct_name, "status": "failed",
                        "ticket": pos.ticket, "reason": result.error,
                    })
        return results

    # ── PENDING ORDER CLEANUP ───────────────────────────────────────────

    async def cleanup_expired_orders(self) -> list[dict]:
        """Cancel expired pending orders. Checks MT5 state first (REL-04)."""
        expired = await db.get_expired_pending_orders()
        results = []
        for order in expired:
            acct_name = order["account_name"]
            connector = self.connectors.get(acct_name)
            if not connector or not connector.connected:
                continue

            # REL-04: Check MT5 state before cancelling
            mt5_orders = await connector.get_pending_orders(order["symbol"])
            mt5_tickets = {o["ticket"] for o in mt5_orders}

            if order["ticket"] not in mt5_tickets:
                # Order no longer pending on MT5 — check if it filled
                positions = await connector.get_positions(order["symbol"])
                filled = any(
                    p.comment and str(order["ticket"]) in p.comment
                    for p in positions
                )
                if filled:
                    await db.mark_pending_filled(order["ticket"], acct_name)
                    logger.info(
                        "%s: Expired order #%d was filled on MT5",
                        acct_name, order["ticket"],
                    )
                    results.append({
                        "account": acct_name, "status": "filled",
                        "ticket": order["ticket"], "symbol": order["symbol"],
                    })
                else:
                    await db.mark_pending_cancelled(order["id"])
                    logger.info(
                        "%s: Expired order #%d already removed from MT5",
                        acct_name, order["ticket"],
                    )
                    results.append({
                        "account": acct_name, "status": "cancelled",
                        "ticket": order["ticket"], "symbol": order["symbol"],
                    })
                continue

            # Order still pending on MT5 — cancel it
            result = await connector.cancel_pending(order["ticket"])
            await db.increment_daily_stat(acct_name, "server_messages")
            if result.success:
                await db.mark_pending_cancelled(order["id"])
                results.append({
                    "account": acct_name, "status": "cancelled",
                    "ticket": order["ticket"], "symbol": order["symbol"],
                })
                logger.info(
                    "%s: Cancelled expired limit order #%d (%s)",
                    acct_name, order["ticket"], order["symbol"],
                )
            else:
                # Cancel failed — will retry next cycle
                logger.warning(
                    "%s: Failed to cancel order #%d: %s — will retry",
                    acct_name, order["ticket"], result.error,
                )
                results.append({
                    "account": acct_name, "status": "cancel_failed",
                    "ticket": order["ticket"], "symbol": order["symbol"],
                    "reason": result.error,
                })
        return results
