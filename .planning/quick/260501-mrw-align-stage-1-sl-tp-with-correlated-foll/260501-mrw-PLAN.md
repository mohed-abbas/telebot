---
phase: quick-260501-mrw
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - db.py
  - trade_manager.py
  - tests/test_trade_manager.py
autonomous: true
requirements:
  - QUICK-260501-mrw — Align stage-1 SL/TP with correlated follow-up
must_haves:
  truths:
    - "When a correlated follow-up arrives and stage 1 is filled, the existing stage-1 MT5 position is modified so its SL matches the follow-up's jittered SL."
    - "When the follow-up carries a TP, the stage-1 position's TP is updated to the jittered follow-up TP."
    - "When stage 1 is missing, not yet filled, or has no MT5 ticket, no modify_position call is made and band creation still proceeds."
    - "If the modify_position call fails (broker reject), bands 2..N still get created and fired (failure isolation, D-17)."
    - "An audit row (signal_type='modify_sl_tp') is recorded on successful stage-1 align so the operator can see the action in the signals log."
  artifacts:
    - path: "db.py"
      provides: "get_stage_by_signal_account(signal_id, account_name, stage_number) helper"
      contains: "async def get_stage_by_signal_account"
    - path: "trade_manager.py"
      provides: "stage-1 SL/TP alignment block inside _handle_correlated_followup"
      contains: "modify_position"
    - path: "tests/test_trade_manager.py"
      provides: "4 regression tests for stage-1 alignment behavior"
      contains: "test_followup_aligns_stage1"
  key_links:
    - from: "trade_manager.py:_handle_correlated_followup"
      to: "db.get_stage_by_signal_account"
      via: "lookup of stage-1 row by (paired_signal_id, acct_name, 1)"
      pattern: "get_stage_by_signal_account\\(paired_signal_id"
    - from: "trade_manager.py:_handle_correlated_followup"
      to: "connector.modify_position"
      via: "MT5 SL/TP update on stage-1 ticket before band creation"
      pattern: "connector\\.modify_position\\("
    - from: "trade_manager.py:_handle_correlated_followup"
      to: "calculate_sl_with_jitter / calculate_tp_with_jitter"
      via: "same jitter function used for the new bands"
      pattern: "calculate_sl_with_jitter\\(signal\\.sl"
---

<objective>
Fix the bug where a correlated follow-up signal does not modify the already-open stage-1 position. After this plan: when the follow-up arrives, stage 1's MT5 position is modified to use the follow-up's jittered SL and TP, so all stages of a single trade share the same exit plan.

Purpose: Operator UAT on 2026-05-01 showed stage 1 keeping its `default_sl_pips`-derived SL and an empty TP while bands 2/3 used the follow-up's plan — visually misaligned and operationally wrong. The fix aligns stage 1 with the rest of the trade.

Output:
- New DB helper `db.get_stage_by_signal_account` (multi-account-safe lookup).
- New stage-1 alignment block at the top of `_handle_correlated_followup` (per account, before bands are computed).
- Four new regression tests in `tests/test_trade_manager.py`.

Out of scope (operator-confirmed):
- `stage_lot_size()` / `_execute_open_on_account` lot-size code stays untouched (lot semantics are intentional).
- Latent multi-account bug in `_handle_text_only_open:313` (mt5_comment UNIQUE collision across accounts) — recorded as a deferred item below; do NOT fix here.
- No SL/TP columns added to `staged_entries` (snapshot_settings already captures fill-time state).
- No `trades` table SL/TP backfill (dashboard reads positions live from MT5).
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/quick/260501-i7u-fix-xauusd-pip-size-and-add-fixed-lot-or/260501-i7u-PLAN.md
@.planning/debug/text-only-stops-fixed-lot.md

# Source files we modify
@trade_manager.py
@db.py

# Existing test patterns to follow
@tests/test_trade_manager.py

<interfaces>
<!-- Key contracts the executor needs. Use these directly — no exploration needed. -->

From `risk_calculator.py` (already imported at trade_manager.py:30):
```python
def calculate_sl_with_jitter(sl: float, jitter_points: float, direction: Direction) -> float
def calculate_tp_with_jitter(tp: float, jitter_points: float, direction: Direction) -> float
# Both return the input unchanged when jitter_points == 0.
```

From `mt5_connector.py:694` (RestApiConnector) and matching `MT5Connector` ABC:
```python
async def modify_position(
    self, ticket: int, sl: float | None = None, tp: float | None = None
) -> OrderResult
# Returns OrderResult(success=bool, ticket=int, error=str|None).
```

From `db.py:1129` (existing analog — copy this style for the new helper):
```python
async def get_stage_by_comment(mt5_comment: str) -> dict | None:
    """D-25 idempotency probe — look up a stage by its canonical mt5_comment."""
    row = await _pool.fetchrow(
        "SELECT id, signal_id, stage_number, account_name, symbol, direction, "
        "status, mt5_ticket FROM staged_entries WHERE mt5_comment=$1",
        mt5_comment,
    )
    return dict(row) if row else None
```

From `db.py:217-241` (staged_entries schema — relevant columns):
```sql
id SERIAL PRIMARY KEY,
signal_id INTEGER NOT NULL,
stage_number INTEGER NOT NULL,
account_name TEXT NOT NULL,
status TEXT NOT NULL DEFAULT 'awaiting_zone',  -- 'filled' is what we filter on
mt5_ticket BIGINT,                              -- NULL until broker confirms
mt5_comment TEXT NOT NULL UNIQUE                -- collides across accounts (deferred bug)
```

From `trade_manager.py:30-34`:
```python
from risk_calculator import (
    calculate_lot_size,
    calculate_sl_distance,
    calculate_sl_with_jitter,
    calculate_tp_with_jitter,
)
```
(jitter helpers are already in scope — no new imports needed.)

From `trade_manager.py` self attributes used in the function:
- `self.cfg.sl_tp_jitter_points: float` — the jitter magnitude
- `self.connectors: dict[str, MT5Connector]`
- `self.accounts: dict[str, AccountConfig]`

From `db.log_signal` (db.py:255 — used for the audit row):
```python
async def log_signal(
    raw_text: str, signal_type: str, action_taken: str,
    symbol: str = "", direction: str = "",
    entry_zone_low: float = 0.0, entry_zone_high: float = 0.0,
    sl: float = 0.0, tp: float = 0.0,
    details: str = "", source_name: str = "",
) -> int
```
</interfaces>

<deferred_items>
<!-- Do NOT fix in this plan. Recorded for future quick task. -->
- **Multi-account stage-1 mt5_comment UNIQUE collision**: `_handle_text_only_open:313` builds `comment = f"telebot-{signal_id}-s1"` without the account name. With multiple accounts enabled, the second account's stage-1 insert will violate the `mt5_comment UNIQUE` constraint and silently skip. Operator runs single-account today, so this is dormant. The new `get_stage_by_signal_account(signal_id, account, 1)` helper added by this plan is the right shape to fix it later (account-scoped lookup). Track as a future quick task.
</deferred_items>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Add get_stage_by_signal_account helper, align stage 1 SL/TP in _handle_correlated_followup, and add 4 regression tests</name>
  <files>db.py, trade_manager.py, tests/test_trade_manager.py</files>
  <behavior>
    Test 1 — `test_followup_aligns_stage1_sl_and_tp_when_filled`:
      - Pre-seed staged_entries with stage 1 (signal_id=99, account=seeded, stage_number=1, status='filled', mt5_ticket=12345).
      - Patch `db.get_stage_by_signal_account` (or use real db if integration-style) to return that row.
      - Spy on `connector.modify_position` via `AsyncMock(return_value=OrderResult(success=True, ticket=12345))`.
      - Build a follow-up SignalAction with direction=BUY, entry_zone=(4570.0, 4572.0), sl=4565.0, target_tp=4580.0.
      - Call `tm._handle_correlated_followup(signal, paired_signal_id=99)`.
      - Assert `connector.modify_position.await_count == 1`.
      - Assert it was called with `ticket=12345`, `sl == calculate_sl_with_jitter(4565.0, jitter, BUY)`, `tp == calculate_tp_with_jitter(4580.0, jitter, BUY)`.
      - Assert results contain a `{"status": "stage1_aligned", "ticket": 12345, ...}` entry.

    Test 2 — `test_followup_skips_stage1_align_when_not_filled`:
      - Stage 1 lookup returns row with `status='awaiting_zone'` AND `mt5_ticket=None`.
      - Spy on `connector.modify_position`.
      - Call `_handle_correlated_followup`.
      - Assert `connector.modify_position.await_count == 0`.
      - Assert no `stage1_aligned` or `stage1_align_failed` entries in results.
      - Assert band-creation path still ran (results contain a "staged" entry).

    Test 3 — `test_followup_continues_band_fill_when_stage1_align_fails`:
      - Stage 1 lookup returns filled row with ticket=12345.
      - `connector.modify_position` returns `OrderResult(success=False, ticket=12345, error="broker reject")`.
      - Call `_handle_correlated_followup`.
      - Assert results contain `{"status": "stage1_align_failed", "ticket": 12345, "reason": "broker reject"}`.
      - Assert results ALSO contain the normal "staged" summary (band creation didn't abort — D-17 failure isolation).

    Test 4 — `test_followup_with_no_tp_still_aligns_stage1_sl`:
      - Follow-up signal has `sl=4565.0` but `target_tp=None` (rare but possible).
      - Stage 1 filled with ticket=12345.
      - Spy on `connector.modify_position`.
      - Assert called with `sl=jittered_sl, tp=0.0` (the modify call still goes through; tp=0.0 means "leave TP unset / clear").
      - Assert no exception from `calculate_tp_with_jitter(None, ...)` — the alignment block must guard against None target_tp.

    Use the same fixture/mocking patterns as the existing `tests/test_trade_manager.py:240-320` block (AsyncMock + monkeypatch on `tm_mod.db.*`). The MockMT5Connector style at top of file (`tests/test_trade_manager.py:13-130`) is fine for the connector fixture, OR replace `connector.modify_position` with `AsyncMock(...)` directly on the existing fixture connector — pick whichever is shorter.
  </behavior>
  <action>
**Step 1 — Add DB helper to `db.py`** (place immediately after `get_stage_by_comment` at db.py:1136):

```python
async def get_stage_by_signal_account(
    signal_id: int, account_name: str, stage_number: int,
) -> dict | None:
    """Multi-account-safe stage lookup — used by correlated-followup stage-1 alignment.

    Returns the stage row for (signal_id, account_name, stage_number) or None.
    Selected because mt5_comment UNIQUE makes get_stage_by_comment() collide
    across accounts; this is the correct shape for per-account stage lookups.
    """
    row = await _pool.fetchrow(
        "SELECT id, signal_id, stage_number, account_name, symbol, direction, "
        "status, mt5_ticket FROM staged_entries "
        "WHERE signal_id=$1 AND account_name=$2 AND stage_number=$3",
        signal_id, account_name, stage_number,
    )
    return dict(row) if row else None
```

**Step 2 — Insert stage-1 alignment block in `trade_manager.py:_handle_correlated_followup`**.

Insert location: inside the `for acct_name, connector in self.connectors.items():` loop (starts at trade_manager.py:383), AFTER the snapshot fetch (trade_manager.py:391-394) and BEFORE the `max_stages = ...` line at trade_manager.py:395.

Why early: surface failures before band-creation work; align the live MT5 view first; the new bands take a moment longer to fire.

Add this block (note: failure isolation per D-17 — never raise; never abort band creation):

```python
# ── Stage-1 SL/TP alignment (operator UAT 2026-05-01) ─────────────
# When the follow-up arrives, modify the already-open stage-1 position
# so SL/TP match the follow-up's plan. Skip silently if stage 1 is
# missing, not yet filled, or has no broker ticket. Failure-isolated
# (D-17): a modify failure must not abort band creation/firing.
stage1 = await db.get_stage_by_signal_account(paired_signal_id, acct_name, 1)
if (
    stage1
    and stage1.get("status") == "filled"
    and stage1.get("mt5_ticket")
):
    new_sl = calculate_sl_with_jitter(
        signal.sl, self.cfg.sl_tp_jitter_points, signal.direction,
    )
    new_tp = 0.0
    if signal.target_tp:
        new_tp = calculate_tp_with_jitter(
            signal.target_tp, self.cfg.sl_tp_jitter_points, signal.direction,
        )
    try:
        modify_result = await connector.modify_position(
            stage1["mt5_ticket"], sl=new_sl, tp=new_tp,
        )
    except Exception as exc:  # never let a connector error abort bands
        logger.warning(
            "%s: stage-1 align raised — continuing with bands: %s",
            acct_name, exc,
        )
        modify_result = OrderResult(
            success=False, ticket=stage1["mt5_ticket"], error=str(exc),
        )
    if modify_result.success:
        logger.info(
            "%s: stage-1 aligned ticket=%d sl=%.5f tp=%.5f",
            acct_name, stage1["mt5_ticket"], new_sl, new_tp,
        )
        results.append({
            "account": acct_name,
            "status": "stage1_aligned",
            "ticket": stage1["mt5_ticket"],
            "sl": new_sl,
            "tp": new_tp,
        })
        try:
            await db.log_signal(
                raw_text=signal.raw_text or "",
                signal_type="modify_sl_tp",
                action_taken=f"stage1_aligned ticket={stage1['mt5_ticket']}",
                symbol=signal.symbol,
                direction=signal.direction.value,
                sl=new_sl,
                tp=new_tp,
                source_name=source_name,
            )
        except Exception as exc:  # audit row failure must not abort
            logger.warning("%s: stage-1 align audit log failed: %s", acct_name, exc)
    else:
        logger.warning(
            "%s: stage-1 align FAILED ticket=%s reason=%s",
            acct_name, stage1.get("mt5_ticket"), modify_result.error,
        )
        results.append({
            "account": acct_name,
            "status": "stage1_align_failed",
            "ticket": stage1["mt5_ticket"],
            "reason": modify_result.error,
        })
else:
    logger.debug(
        "%s: skipping stage-1 align (stage1=%s)",
        acct_name, stage1,
    )
```

No new imports needed: `calculate_sl_with_jitter` and `calculate_tp_with_jitter` are imported at trade_manager.py:30-34; `OrderResult` at trade_manager.py:28; `db` at trade_manager.py:19; `logger` at trade_manager.py:36.

**Step 3 — Add 4 regression tests to `tests/test_trade_manager.py`**.

Append a new test class (e.g., `class TestCorrelatedFollowupStage1Align:`) at the end of the file. Follow the AsyncMock + monkeypatch pattern already used by `TestFixedLotMode` (tests/test_trade_manager.py:240-320). For each test:

- monkeypatch `tm_mod.db.get_stage_by_signal_account` with `AsyncMock(return_value=...)` to control the stage-1 lookup
- monkeypatch `tm_mod.db.create_staged_entries` with `AsyncMock(return_value=[1, 2])` so band insertion doesn't hit a real DB
- monkeypatch `tm_mod.db.log_signal` with `AsyncMock(return_value=1)` for the audit row
- monkeypatch `tm_mod.db.update_stage_status` with `AsyncMock(return_value=None)`
- replace `connector.modify_position` with an `AsyncMock` and inspect `.await_args` / `.await_count`
- replace `connector.get_price` with `AsyncMock(return_value=(4571.0, 4571.5))` so the bands branch can run

Each test asserts the precise behavior listed in the `<behavior>` block above.
  </action>
  <verify>
    <automated>uv run pytest tests/test_trade_manager.py -v -k "stage1_align or followup_aligns or followup_skips or followup_continues or followup_with_no_tp"</automated>
    <automated>uv run pytest tests/test_trade_manager.py -v</automated>
  </verify>
  <done>
- `db.get_stage_by_signal_account` exists and returns dict|None.
- `_handle_correlated_followup` modifies stage-1 position with jittered SL and (jittered or 0.0) TP when stage 1 is filled with a ticket.
- Modify happens BEFORE band creation/firing.
- Modify failure does NOT abort band creation (D-17 failure isolation).
- 4 new tests pass.
- All previously-passing tests in `tests/test_trade_manager.py` still pass.
- The pre-existing failure in `tests/test_rest_api_connector.py::TestConnect::test_connect_sends_correct_json_and_sets_connected` (documented in the prior 260501-i7u SUMMARY) is the only acceptable smoke-test failure.
  </done>
</task>

</tasks>

<verification>
**Manual operator UAT (deferred to live MT5 — per `feedback_commit_timing.md`, no commit until operator confirms):**

1. On Vantage Demo-10k, send `Gold buy now` (text-only) — wait for stage 1 to fill (dashboard shows ticket + SL=default-derived, TP=—).
2. Send the structured follow-up (zone+SL+TP).
3. Within ~3s the dashboard should show:
   - Stage 1 ticket: SL = jittered(follow-up.SL), TP = jittered(follow-up.TP) — i.e. SL/TP visually aligned with stages 2/3.
   - Stages 2/3: same as before (jittered follow-up SL/TP).
4. Inspect `signals` table: a row with `signal_type='modify_sl_tp'` and `action_taken` containing `stage1_aligned ticket=...`.
5. Negative path (optional): repeat with a follow-up sent BEFORE stage 1 fills — confirm no errors, bands still get created, no `stage1_align_failed` row.

**Automated:**
- `uv run pytest tests/test_trade_manager.py -v` — all green.
- `uv run pytest -x` — only the documented pre-existing rest_api_connector failure remains.
</verification>

<success_criteria>
- All 4 new tests in `tests/test_trade_manager.py` pass.
- No regressions in `tests/test_trade_manager.py`.
- Operator confirms live behavior matches expectation on Vantage Demo-10k.
- No commit until operator confirms (per `feedback_commit_timing.md`).
- Commit message (when made) has NO `Co-Authored-By` footer (per `feedback_no_coauthor.md`).
</success_criteria>

<output>
After completion, create `.planning/quick/260501-mrw-align-stage-1-sl-tp-with-correlated-foll/260501-mrw-SUMMARY.md` with:
- What changed (db helper + alignment block + tests)
- Test results
- Pending operator UAT status
- Deferred item recap (multi-account stage-1 mt5_comment collision)
</output>
