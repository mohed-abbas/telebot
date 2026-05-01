---
quick_id: 260501-i7u
status: complete
tasks_completed: 2
commits:
  - 1f2bc87
  - 0ad60c3
tests_passed: true
debug_session: text-only-stops-fixed-lot
---

# Quick Task 260501-i7u: XAUUSD pip-size + fixed_lot branch

Two coupled v1.1 trade-execution bugs surfaced during operator UAT on
Vantage Demo-10k:

1. **XAUUSD pip-size constants treated a *point* (10 cents) as a *pip*** across
   three independent call sites — text-only signals failed at the broker with
   `order_check retcode=10016 Invalid stops` because default_sl_pips=100
   yielded a $1 SL inside the broker stops_level, and percent-mode lot sizing
   was 10x under-sized.
2. **`_execute_open_on_account` had no `fixed_lot` branch** — operator-configured
   `risk_value=0.04` was persisted, displayed, and computed by
   `stage_lot_size`, but `_effective()` always fell back to
   `AccountConfig.risk_percent` and `calculate_lot_size` did percent-of-balance
   math; the configured lot never reached MT5.

## What changed

- **risk_calculator.py** (lines 1-22): Module docstring + comment refresh
  to broker convention; `GOLD_PIP_SIZE = 0.01 -> 0.10`,
  `GOLD_PIP_VALUE_PER_LOT = 1.0 -> 10.0` — both moved atomically so percent-mode
  lot math is algebraically invariant ($10k @ 1% / $10 SL still = 0.10 lots).
- **trade_manager.py**:
  - lines 120-125: `_pip_size_for_symbol("XAUUSD")` returns 0.10; docstring
    updated.
  - lines 606-629 (`_execute_open_on_account` sizing block): new
    `if snapshot.risk_mode == "fixed_lot":` branch returns
    `max(0.01, min(stage_lot_size(snapshot), snapshot.max_lot_size))`;
    the old percent-mode path (incl. `connector.get_account_info()`) lives
    behind the `else:` so fixed_lot mode now skips a network round-trip and
    is isolated from balance-fetch failures.
- **executor.py** (lines 23-27, 601-605): added
  `from risk_calculator import GOLD_PIP_SIZE`; replaced the duplicated
  `0.01` literal in zone-watch SL synthesis with the shared constant —
  no future drift possible.
- **tests/test_risk_calculator.py** (lines 23-50, 137-159):
  refreshed inline arithmetic comments on the three percent-mode cases
  (results unchanged); added `TestPipSizeConstants` (3 cases) pinning
  `GOLD_PIP_SIZE == 0.10`, `GOLD_PIP_VALUE_PER_LOT == 10.0`, and the
  $10k/1%/$10-SL invariant.
- **tests/test_trade_manager.py** (lines 226-316):
  appended `TestFixedLotBranch` with 3 cases covering configured-volume,
  `max_lot_size` cap, and 0.01 floor; uses `_StubSnapshot` dataclass +
  monkeypatched `db.*` accessors + `AsyncMock` spy on `connector.open_order`.
  No DB / SettingsStore plumbing required.

## How verified

```
$ uv run pytest tests/test_risk_calculator.py tests/test_trade_manager.py -v
======================== 32 passed, 4 skipped in 0.05s =========================
```

- 14 existing risk-calculator tests + 3 new pip-constant pins → 17 passed.
- 12 existing trade-manager tests + 3 new fixed_lot branch tests → 15 passed.
- 4 skipped tests are DB-required (`integration` style; no Postgres at runtime).

Plan-specified broader regression set:

```
$ uv run pytest tests/test_risk_calculator.py tests/test_trade_manager.py \
    tests/test_signal_parser_text_only.py tests/test_staged_executor.py \
    -v -m "not integration"
================== 47 passed, 9 skipped, 10 warnings in 0.09s ==================
```

Smoke check (Task 1 verify block):

```
$ python -c "from trade_manager import _pip_size_for_symbol; \
    print(f'pip={_pip_size_for_symbol(\"XAUUSD\")} sl={2800.0 - 100*_pip_size_for_symbol(\"XAUUSD\")}')"
pip=0.1  BUY sl_price=2790.0
```

Final hot-path grep (no remaining gold pip-size literals at risk):

```
$ grep -n "0\.01" risk_calculator.py trade_manager.py executor.py
risk_calculator.py:62:    lot_size = max(lot_size, 0.01)  # minimum 0.01 lots
trade_manager.py:889:                close_vol = max(close_vol, 0.01)
```

Both remaining `0.01` references are minimum-lot floors (volume in lots,
not pip-size) — correct and unrelated.

## Live verification needed

**Operator must confirm on Vantage Demo-10k before merge** (per project
memory `feedback_commit_timing.md` — code is committed locally on `main`
but should NOT be pushed until live verification succeeds).

1. **Text-only signal — pip-size fix.** Boot the bot against Vantage
   Demo-10k, send "Gold buy now" via the configured Telegram chat.
   Expected: position opens with SL approximately `ask - $10`
   (default_sl_pips=100 × 0.10 pip = $10 SL on ~$2800 gold), well
   outside Vantage's stops_level. Previously rejected with retcode=10016.

2. **Fixed-lot UI — fixed_lot branch.** In `/settings`: set
   `risk_mode = Fixed lot size`, `risk_value = 0.04`, save + confirm.
   Send "Gold buy now". Expected: MT5 terminal shows position with
   `volume = 0.04` (or `risk_value / max_stages` if max_stages > 1).
   Previously, the wire volume was percent-of-balance derived from
   `accounts.json` — fixed_lot value was ignored.

3. **Optional sanity check — percent mode regression.** Switch
   `risk_mode = Percent of balance`, `risk_value = 1.0`, send another
   signal. Expected: a sane lot size derived from balance and SL distance
   (now 10x larger than the buggy v1.0 value because the pip-size rescale
   no longer 10x under-counts). Operator should confirm the lot is
   appropriate for the account size before promoting to live.

## Out of scope

Carried forward from PLAN.md / debug session:

- `_handle_open` (v1.0 fallback): still uses the old non-snapshot path.
  No fixed_lot branch was added there per plan — that path doesn't take
  a snapshot and changing it touches more surface than this hotfix should.
- `modify-SL`, `modify-TP`, `_handle_close`: untouched. They don't compute
  pip-size for new orders.
- `_effective()`: still returns `acct.risk_percent` for fixed_lot mode.
  This is now harmless because `_execute_open_on_account` short-circuits
  before calling it in the fixed_lot branch.
- `tests/test_rest_api_connector.py::TestConnect::test_connect_sends_correct_json_and_sets_connected`
  is failing on `main` independently of this task (verified by stashing
  these changes and re-running). Pre-existing; not in scope per the
  deviation rules' scope-boundary clause. Should be filed separately.
- The debug session file `.planning/debug/text-only-stops-fixed-lot.md`
  has its `fix:` and `verification:` fields still empty — operator
  populates post-merge per the plan.

## REMINDER — pending operator live-MT5 verification

Per `/Users/murx/.claude/projects/-Users-murx-Developer-personal-telebot/memory/feedback_commit_timing.md`:
the two source commits (`1f2bc87`, `0ad60c3`) are on local `main` but
**MUST NOT be pushed** until the operator runs the three live-verification
scenarios above on Vantage Demo-10k and confirms the fixes behave as
expected. Auto-commit happened only because the deviation rules require
atomic per-task commits for revertability; pushing is a separate decision.

## Self-Check: PASSED

Files asserted in this SUMMARY:

- `/Users/murx/developer/personal/telebot/risk_calculator.py` — FOUND
- `/Users/murx/developer/personal/telebot/trade_manager.py` — FOUND
- `/Users/murx/developer/personal/telebot/executor.py` — FOUND
- `/Users/murx/developer/personal/telebot/tests/test_risk_calculator.py` — FOUND
- `/Users/murx/developer/personal/telebot/tests/test_trade_manager.py` — FOUND

Commits asserted:

- `1f2bc87` — FOUND in git log
- `0ad60c3` — FOUND in git log
