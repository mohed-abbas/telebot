---
slug: text-only-stops-fixed-lot
status: root_cause_found
trigger: |
  Two coupled bugs in v1.1 trade execution surfaced after live testing on Vantage Demo-10k:
    1. Every text-only signal ("Gold buy now" / "Gold sell now") fails on the broker with
       "order_check retcode=10016 Invalid stops" — Discord webhook line:
         OPEN_TEXT_ONLY XAUUSD
           Vantage Demo-10k: FAILED — order_check retcode=10016 Invalid stops
    2. Operator set risk_mode=fixed_lot, risk_value=0.04 in /settings. The value persists
       in the DB and renders correctly in the UI, but actual orders sent to MT5 use a
       different volume — the configured 0.04 is ignored on the wire.
    3. The default stop-loss configured for text-only signals (default_sl_pips) is also
       not behaving like operator expects — likely the same root cause as (1).
created: 2026-05-01
updated: 2026-05-01
---

# Debug: text-only-stops-fixed-lot

## Symptoms

- **Expected:**
  1. Text-only signal "Gold buy now" → exactly one position opens on each enabled account
     with a valid SL (default_sl_pips converted to a price distance the broker accepts).
  2. With risk_mode=fixed_lot and risk_value=0.04, every order sent to MT5 has
     volume=0.04 (capped at max_lot_size, floored at 0.01).
  3. default_sl_pips setting controls the actual SL distance for text-only fills.
- **Actual:**
  1. Text-only signal returns "FAILED — order_check retcode=10016 Invalid stops" on
     Vantage Demo-10k. No position opens. Discord webhook posts the failure.
  2. Order volume on the wire is whatever calculate_lot_size() computes from
     accounts.json risk_percent + balance / sl_distance — NOT 0.04.
  3. SL is too close to current price; broker rejects (same retcode 10016).
- **Errors:**
  - `OPEN_TEXT_ONLY XAUUSD` / `Vantage Demo-10k: FAILED — order_check retcode=10016 Invalid stops`
  - Comes from mt5-rest-server/server.py:326 (`order_check retcode={check.retcode} {check.comment}`)
- **Timeline:** Reported 2026-05-01 during operator UAT for milestone v1.1 (Phases 5–7
  complete). Bugs are in the v1.1 staged-entry / settings paths shipped in Phase 6.
- **Reproduction:**
  - Bug 1/3: Send any text-only signal ("Gold buy now") via Telegram while
    Vantage Demo-10k is connected → broker rejects with 10016.
  - Bug 2: On /settings page, set risk_mode=Fixed lot size, risk_value=0.04, save
    and confirm. Then send any open signal → MT5 trade volume ≠ 0.04.
- **Account in use:** Vantage Demo-10k

## Initial Hypothesis (from main-context investigation, to be verified)

### Bug 1 + 3 (Invalid stops + SL not respecting setting)
Pip-size unit is wrong for XAUUSD across the codebase. Three call sites treat 1 gold
"pip" as $0.01 (which is actually a *point*, not a pip). With default_sl_pips=100
and pip_size=0.01 the SL ends up only $1.00 from price — well inside Vantage's
stops_level. Affected files:
- `risk_calculator.py:21` — `GOLD_PIP_SIZE = 0.01`
- `trade_manager.py:120-125` — `_pip_size_for_symbol("XAUUSD") == 0.01`
- `executor.py:603` — `pip_size = 0.01 if symbol.upper() == "XAUUSD" else 0.0001`

Predicted fix: 1 pip XAUUSD = $0.10 (10 points). Lot-size math also affected
(over-counts pips by 10× → under-sizes lot by 10× in percent mode).

### Bug 2 (fixed_lot lot size ignored)
`fixed_lot` is plumbed through UI → DB → SettingsStore → `stage_lot_size()`, but the
order-sizing path `_execute_open_on_account` only ever calls `calculate_lot_size()`,
which has no `fixed_lot` branch. `_effective()` even acknowledges this in a comment
(`trade_manager.py:137-138`) without acting on it. `stage_lot_size()` value is only
used to populate `staged_entries.target_lot` for display — never reaches MT5.

Predicted fix: branch in `_execute_open_on_account` (around line 614):
- `risk_mode=='fixed_lot'` → `lot_size = stage_lot_size(snapshot)` (cap at max_lot_size, floor at 0.01)
- `risk_mode=='percent'` → existing `calculate_lot_size(...)` call.

## Current Focus

```yaml
hypothesis: |
  CONFIRMED. Two independent root causes in trade_manager.py / risk_calculator.py /
  executor.py — pip-size constant treats a *point* as a *pip* (10× off), and
  _execute_open_on_account has no fixed_lot branch.
test: completed via direct code re-trace of all call sites.
expecting: |
  Pip-size correction (0.01 → 0.10) propagates through default-SL math (text-only)
  AND through calculate_lot_size's sl_pips division. Adding a fixed_lot branch in
  _execute_open_on_account routes operator-configured lot to the wire.
next_action: |
  Present fix options to operator. No premature commit (per project memory).
reasoning_checkpoint: ""
tdd_checkpoint: ""
```

## Evidence

- timestamp: 2026-05-01
  source: main-context grep + read of trade_manager.py:307-311, risk_calculator.py:21,
          executor.py:603, mt5-rest-server/server.py:309-327
  finding: |
    Text-only path (trade_manager.py:307-311) computes
      sl_price = ask - (default_sl_pips * pip_size)
    where pip_size = _pip_size_for_symbol("XAUUSD") = 0.01 and default_sl_pips
    defaults to 100. Result: SL is $1.00 below price for gold trading at ~$2,800.
    mt5-rest-server/server.py order_send wrapper calls mt5.order_check(request)
    (line 312) and returns "order_check retcode={check.retcode} {check.comment}"
    on non-zero retcode (line 326) — exact format matches Discord error.
- timestamp: 2026-05-01
  source: trade_manager.py:107-148, risk_calculator.py:24-62
  finding: |
    stage_lot_size(snapshot) returns risk_value/max_stages for fixed_lot, but only
    populates staged_entries.target_lot (lines 325, 415). The actual order sizing
    in _execute_open_on_account (line 614) calls _effective() then calculate_lot_size().
    _effective (line 144): "risk_percent = s.risk_value if s.risk_mode == 'percent'
    else acct.risk_percent" — falls back to JSON risk_percent for fixed_lot.
    calculate_lot_size has no fixed_lot branch — only does percent-of-balance math.
    Comment at trade_manager.py:137-138 acknowledges fixed_lot semantics that the
    code never implements.
- timestamp: 2026-05-01
  source: full re-trace of trade_manager.py:107-148, 257-358, 500-720; risk_calculator.py:1-62;
          executor.py:580-680; settings_store.py:55-85; models.py:76-94
  finding: |
    Bug 1/3 — pip-size CONFIRMED. Three independent constants set to 0.01 (a point,
    not a pip):
      • risk_calculator.py:21 GOLD_PIP_SIZE = 0.01 (used inside calculate_lot_size:50
        as `sl_pips = sl_distance / GOLD_PIP_SIZE`).
      • trade_manager.py:122-123 _pip_size_for_symbol("XAUUSD") returns 0.01 (used at
        307-311 to convert default_sl_pips → SL price for text-only fills).
      • executor.py:603 hard-coded `0.01 if symbol.upper()=="XAUUSD" else 0.0001`
        (used at 607-611 inside _zone_watch_loop's stage-fire path for SL synth).
    With default_sl_pips=100 (default) the SL distance is 100*0.01 = $1.00. Vantage
    Demo-10k for XAUUSD typically has trade_stops_level in the 30-200 point range
    (= $0.30-$2.00). $1.00 lands inside or right at the edge → 10016 Invalid stops.
    Even if it didn't trip 10016, the operator-facing semantics are broken: the
    docstring at risk_calculator.py:4-6 ("1 pip = $0.01") is inverted from broker
    convention (1 gold pip = $0.10 = 10 points) and confuses /settings consumers.
    The pip-size error also under-sizes lots by 10× in percent mode (calculate_lot_size:50
    over-counts pips by 10×, so risk_amount/(sl_pips*1) is 10× too small).

    Bug 2 — fixed_lot CONFIRMED. End-to-end re-trace:
      1. UI POST /settings writes risk_mode='fixed_lot', risk_value=0.04 → DB.
      2. SettingsStore.reload() loads it into AccountSettings dataclass
         (settings_store.py:59-68).
      3. trade_manager._handle_text_only_open() snapshots the AccountSettings
         (line 298) and stores it in staged_entries.snapshot_settings + computes
         target_lot = stage_lot_size(snapshot) = 0.04/max_stages (line 325).
      4. _handle_text_only_open() then calls _execute_open_on_account(snapshot=snapshot)
         (line 347-350).
      5. _execute_open_on_account (line 614) ignores `snapshot.risk_mode` entirely.
         It calls `risk_pct, max_lot, _ = _effective(self, acct)` — and _effective
         (line 144) hard-coded falls back to acct.risk_percent (accounts.json) when
         risk_mode != 'percent'.
      6. calculate_lot_size(account_balance, risk_percent=acct.risk_percent, ...)
         then computes a percent-of-balance lot. Fixed-lot value never reaches
         the order_send call at line 692-699.
      The same bug afflicts staged stages 2..N via _zone_watch_loop → executor.py:628.
      stage_lot_size() result is only used for display in staged_entries.target_lot.
      All three signal paths (_handle_open v1.0, _handle_text_only_open,
      _handle_correlated_followup → _execute_open_on_account, and zone_watch fills
      via executor.py) share this single sizing path and are equally broken.

## Eliminated

(none — both initial hypotheses confirmed)

## Resolution

- root_cause: |
    Two independent v1.1 bugs in the same execution stack:
    (1) GOLD_PIP_SIZE / _pip_size_for_symbol / executor.py pip constant all set to
        $0.01 (a "point") instead of $0.10 (a gold "pip"). Default-SL math yields
        a $1 SL on $2800 gold → broker rejects 10016 Invalid stops; lot sizing in
        percent mode is also 10× too small.
    (2) _execute_open_on_account never branches on AccountSettings.risk_mode — it
        always calls calculate_lot_size() with risk_pct from _effective(), which
        falls back to accounts.json when risk_mode != 'percent'. The operator's
        fixed_lot value is computed (stage_lot_size), persisted to staged_entries
        for display, but never plumbed to the MT5 volume.
- fix: ""  # awaiting operator selection of fix path
- verification: ""
- files_changed: []
