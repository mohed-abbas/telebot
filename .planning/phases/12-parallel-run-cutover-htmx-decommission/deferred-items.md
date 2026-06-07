# Phase 12 — Deferred Items (out of scope)

Discovered during 12-03 (CUT-03 teardown) execution. These are pre-existing
failures unrelated to the HTMX/Jinja teardown surface — logged per the executor
SCOPE BOUNDARY rule (only auto-fix issues DIRECTLY caused by the current task).
Confirmed they fail identically at the 12-02 baseline commit (498114a), before
any teardown work.

| Item | Test | Cause | Scope |
|------|------|-------|-------|
| 1 | `tests/test_rest_api_connector.py::TestConnect::test_connect_sends_correct_json_and_sets_connected` | `assert False is True` — MT5 REST connector connect behavior; no dashboard/template/HTMX reference | Pre-existing, MT5 connector — NOT teardown-related |
| 2 | `tests/test_rest_api_connector.py::TestConnect::test_connect_clears_password_on_success` | `AssertionError: assert 'secret' == ''` — connector password-clearing behavior | Pre-existing, MT5 connector — NOT teardown-related |
| 3 | `tests/test_rest_api_integration.py::test_full_market_buy_flow` | `assert False is True` — full market-buy flow integration | Pre-existing, MT5 connector — NOT teardown-related |

These touch the MT5 REST connector, not the dashboard presentation layer. They
existed before Phase 12 began and are unaffected by CUT-03. Left untouched.
