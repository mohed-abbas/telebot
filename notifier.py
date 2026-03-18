"""Multi-channel Discord notifications.

Routes messages to separate Discord channels:
  - #signals:    raw Telegram relay (existing webhook, handled by bot.py)
  - #executions: trade confirmations, fills, closures, P&L
  - #alerts:     errors, connection drops, stale skips, daily limits
"""

from __future__ import annotations

import logging

import httpx

from discord_sender import send_message
from models import SignalAction, SignalType

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(
        self,
        http: httpx.AsyncClient,
        executions_webhook: str | None,
        alerts_webhook: str | None,
    ):
        self.http = http
        self.executions_url = executions_webhook
        self.alerts_url = alerts_webhook

    async def notify_execution(self, signal: SignalAction, results: list[dict]) -> None:
        """Send execution results to #executions channel."""
        if not self.executions_url:
            return

        lines = [self._format_header(signal)]

        for r in results:
            acct = r.get("account", "?")
            status = r.get("status", "?")

            if status == "executed":
                lines.append(
                    f"  {acct}: {r['lot_size']:.2f} lots @ {r['price']:.2f} | "
                    f"SL: {r['sl']:.2f} | TP: {r['tp']:.2f}"
                )
            elif status == "limit_placed":
                lines.append(
                    f"  {acct}: LIMIT @ {r['price']:.2f} | "
                    f"{r['lot_size']:.2f} lots | SL: {r['sl']:.2f} | TP: {r['tp']:.2f}"
                )
            elif status == "closed":
                pnl = r.get("pnl", 0)
                sign = "+" if pnl >= 0 else ""
                lines.append(f"  {acct}: CLOSED #{r['ticket']} | P&L: {sign}${pnl:.2f}")
            elif status == "partial_closed":
                lines.append(
                    f"  {acct}: PARTIAL CLOSE #{r['ticket']} | "
                    f"closed {r['closed_volume']:.2f} lots"
                )
            elif status == "sl_modified":
                lines.append(f"  {acct}: SL → {r['new_sl']:.2f} (#{r['ticket']})")
            elif status == "tp_modified":
                lines.append(f"  {acct}: TP → {r['new_tp']:.2f} (#{r['ticket']})")
            elif status == "skipped":
                lines.append(f"  {acct}: SKIPPED — {r.get('reason', '?')}")
            elif status == "failed":
                lines.append(f"  {acct}: FAILED — {r.get('reason', '?')}")

        msg = "\n".join(lines)
        await send_message(self.http, self.executions_url, msg)

    async def notify_alert(self, message: str) -> None:
        """Send an alert to #alerts channel."""
        if not self.alerts_url:
            logger.warning("No alerts webhook configured: %s", message)
            return
        await send_message(self.http, self.alerts_url, message)

    async def notify_stale_skip(self, signal: SignalAction, reason: str) -> None:
        """Notify that a signal was skipped due to stale check."""
        msg = f"SIGNAL SKIPPED: {reason}\n  Original: {signal.raw_text[:200]}"
        await self.notify_alert(msg)

    async def notify_connection_lost(self, account_name: str, error: str) -> None:
        await self.notify_alert(f"CONNECTION LOST: {account_name} — {error}")

    async def notify_connection_restored(self, account_name: str) -> None:
        await self.notify_alert(f"CONNECTION RESTORED: {account_name}")

    async def notify_daily_limit(self, account_name: str, limit_type: str) -> None:
        await self.notify_alert(
            f"DAILY LIMIT: {account_name} hit {limit_type} — trading paused until tomorrow"
        )

    async def notify_kill_switch(self, activated: bool) -> None:
        state = "ACTIVATED — all trading paused" if activated else "DEACTIVATED — trading resumed"
        await self.notify_alert(f"KILL SWITCH: {state}")

    async def notify_limit_expired(self, account_name: str, ticket: int, symbol: str) -> None:
        await self.notify_alert(
            f"LIMIT EXPIRED: {account_name} order #{ticket} ({symbol}) cancelled — never filled"
        )

    def _format_header(self, signal: SignalAction) -> str:
        if signal.type == SignalType.OPEN:
            dir_str = signal.direction.value.upper() if signal.direction else "?"
            zone = signal.entry_zone
            zone_str = f"{zone[0]:.2f}-{zone[1]:.2f}" if zone else "N/A"
            return f"{dir_str} {signal.symbol} — Zone: {zone_str}"
        elif signal.type == SignalType.CLOSE:
            return f"CLOSE ALL {signal.symbol}"
        elif signal.type == SignalType.CLOSE_PARTIAL:
            pct = signal.close_percent or 50
            return f"CLOSE {pct:.0f}% {signal.symbol}"
        elif signal.type == SignalType.MODIFY_SL:
            if signal.new_sl == 0.0:
                return f"SL TO BREAKEVEN — {signal.symbol}"
            return f"UPDATE SL → {signal.new_sl:.2f} — {signal.symbol}"
        elif signal.type == SignalType.MODIFY_TP:
            return f"UPDATE TP → {signal.new_tp:.2f} — {signal.symbol}"
        return f"{signal.type.value.upper()} {signal.symbol}"
