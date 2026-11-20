# Plan — editable open-trades cap and per-stage TP

Date: 2026-11-18 · Status: **ready** — D1–D5 accepted by the owner on 2026-11-18 · Code changed: none yet

## Outcome

1. The operator can set **Maximum open trades** per account from the dashboard
   Settings page, so all 5 staged entries of a signal can open (today
   `max_stages=5` but `max_open_trades=3`, so entries 4 and 5 always end `capped`).
2. Each staged entry can target its own provider TP (example: entries 1–3 at TP2,
   entries 4–5 at TP3), configured per account in Settings. SL stays the same for
   every entry.

Out of scope: lot weighting per entry, the far-edge trigger, TP-hit parsing,
changes to how breakeven or SL moves work.

## What the code does today (inspected)

| Area | Fact | Where |
|---|---|---|
| Cap storage | `max_open_trades` lives in the `accounts` table, no CHECK; not in `account_settings`; no write path exists | `db.py:171-187`, `db.py:38-40`, `db.py:1072-1100` |
| Cap use | Read **live** (not from the signal snapshot); counts every open position on the symbol, any signal, any direction | `trade_manager.py:1059-1072` |
| Settings pipeline | validate → confirm → audit row per field → revert newest row; server caps in `validate_settings_form` | `api/settings.py`, `dashboard.py:418-478` |
| Revert bug | Revert re-validates through `validate_settings_form`, which returns only the 5 `account_settings` fields → `KeyError` (HTTP 500) for any other field | `api/settings.py:291-301` |
| UI | Field rendered read-only with "Set per account — not editable here" | `frontend/src/components/settings/SettingsForm.tsx:193-206` |
| Snapshot | `AccountSettings` is frozen into `staged_entries.snapshot_settings`; zone-watch rebuilds it with `snapshot_dict[f.name]` for every field → a new field breaks rebuild of older rows | `executor.py:1728-1746` |
| TP choice | One TP per signal: `target_tp` = numeric TP #2 (`signal_keywords.json` `default_target_tp`), fallback to last numeric TP; "open" TPs skipped | `signal_parser.py:244-251, 405-407` |
| TP on stages | Same `signal.target_tp` written to every row's `signal_tp`, to stage-1 alignment, and to at-arrival fires | `trade_manager.py:604-608, 712-735, 751-760, 946-947, 974, 1153-1154` |
| SL/TP sweep | Already per row: holds each filled position at its own row's `signal_tp` | `executor.py:1567-1707` |
| Target cascade | Checks **one arbitrary row per signal** (`get_active_stages` has no ORDER BY) and cancels **all** unfilled rows of that signal | `executor.py:1043-1124`, `db.py:1571-1586` |
| Stage-1 lifetime (D-16) | Stage 1 gone → all unfilled rows of the signal cancelled | `executor.py:526-583` |
| Stage numbering | `compute_bands` ignores direction: stage 2 is always the **lowest** band. SELL fills stage 2 first; **BUY fills the highest stage number first** and stage 2 last | `trade_manager.py:82-134` |
| Management | close / close_partial / modify_tp act on **every** telebot position on the symbol; modify_tp writes one TP to all; armed rows keep their old SL/TP | `trade_manager.py:1528-1766` |
| Old gate | `tests/_bot_core_diff_guard.py` forbids diffs in bot-core files "in v1.2". It is only run explicitly, and bot-core files have changed since (669f4cc, 7de7b0e). Treat it as retired for this work | `tests/_bot_core_diff_guard.py` |

Could not establish here: the live DB values and how often signals overlap on the
same symbol (needs the VPS DB).

## Decisions

| ID | Question | Decision (accepted) | Why |
|---|---|---|---|
| D1 | Max entries > open-trades cap: block or warn? | **Block on save** (`max_stages ≤ max_open_trades`), plus a warning when the cap leaves no room for an overlapping signal | The current state (5 entries, cap 3) silently wastes 2 entries and makes the lot banner wrong |
| D2 | What does "entry 4" mean? | **Fill order** (entry 1 = market fill, entry 2 = first band price meets, entry 5 = deepest). Make `compute_bands` number bands by depth for both directions | Today a BUY's "stage 5" is its *first* fill, so "stages 4–5 → TP3" would put TP3 on the shallowest buys |
| D3 | When price hits a TP, which unfilled entries are cancelled? | **All unfilled entries at the nearest TP of the sequence (or SL)** — today's rule, made deterministic | Once the first target is hit the setup has played out; filled TP3 entries keep running. Per-row cancelling would let deep TP3 entries open after TP2 was hit |
| D4 | Provider partial close ("TP1 hit close half") | **Keep as today**: applies to every position, TP3 entries included | Simple and predictable; revisit after live data |
| D5 | Provider "New TP: X" | **Keep as today**: overwrites the TP of every position | An explicit provider instruction wins over the account mapping |

Fixed (routine) choices:
- TP numbers mean the signal's numeric TPs in message order (today's rule). If a
  signal has fewer TPs than an entry asks for, use the last numeric TP. No TPs →
  no TP, as today.
- Default mapping = TP2 for every entry, so behaviour is unchanged until an
  operator edits it.
- Mapping is stored per account and frozen per signal in the snapshot, like
  `max_stages`.

## Acceptance criteria

Open-trades cap
- **OT-01** Settings shows Maximum open trades as an editable number (1–20); saving
  writes `accounts.max_open_trades`, adds a `settings_audit` row, and the next
  signal uses the new value without a restart.
- **OT-02** Saving `max_stages` greater than `max_open_trades` is rejected with a
  field error naming both values (D1).
- **OT-03** "Revert last change" works for a `max_open_trades` audit row and for
  every `account_settings` field (no 500).
- **OT-04** The lot banner states the real per-signal maximum
  (`min(max_stages, max_open_trades) × per-entry lot`).

Per-stage TP
- **TP-01** Settings shows one TP selector (TP1–TP5) per entry, resized with
  Maximum entries; saved, audited and revertible like other fields.
- **TP-02** With mapping `[2,2,2,3,3]` and a sell follow-up with TP1–TP4, entries
  1–3 open with TP2 and entries 4–5 with TP3, for both the correlated
  (text-only + follow-up) path and the direct-zone path. Stage-1 alignment uses
  entry 1's TP.
- **TP-03** Same as TP-02 for a BUY: entries 4–5 are the two deepest buys (D2).
- **TP-04** A signal with only TP1–TP2 and mapping `[2,2,2,3,3]` gives entries 4–5
  TP2 (last numeric TP).
- **TP-05** The SL/TP sweep keeps each filled entry at its own TP (TP2 entries are
  not moved to TP3 or back).
- **TP-06** When price reaches the nearest TP of the sequence, every unfilled entry
  is cancelled, whichever row the watcher reads first (D3).
- **TP-07** Armed rows created before the deploy (snapshot without the new field)
  still fire with their stored TP; no snapshot-rebuild failure.
- **TP-08** Default mapping reproduces today's orders exactly
  (`test_exact_signal_sl_tp.py` stays green unchanged).
- **TP-09** The /staged page shows each entry's TP.

## Slices

### Slice 1 — Editable open-trades cap (OT-01..04)
- `db.py`: `update_account_column(name, field, value, actor)` with a whitelist
  `{max_open_trades}`, same transaction + audit shape as `update_account_setting`;
  `CHECK (max_open_trades BETWEEN 1 AND 20)` added via `ALTER TABLE ... ADD
  CONSTRAINT` guarded for re-runs.
- `settings_store.update`: route `max_open_trades` to the new function, then reload.
- `dashboard.validate_settings_form`: accept `max_open_trades` (1–20) and the
  cross-field rule from D1; `_compute_dry_run` mentions the effective entry count.
- `api/settings.py`: add the field to the confirm diff; fix revert to re-validate
  from the full current values (fixes OT-03 for every field).
- Frontend: `SettingsForm.tsx` makes the field editable; `settingsSchema.ts` adds
  the range and cross-field rule; `footgun.ts` uses the effective entry count.
- Tests: extend `tests/test_api_settings.py` (confirm + audit + revert for
  `max_open_trades`, cross-field 200/`valid:false`), `tests/test_settings_store.py`
  (cache reload after update), `tests/test_db_schema.py` (CHECK);
  `settingsSchema.test.ts` and `footgun.test.ts` replace the "max_open_trades not
  capped" case.
- Docs: `docs/adding-new-account.md` / `docs/ci-cd.md` say the cap is now edited in
  Settings (accounts.json only seeds new accounts).
- Done when: the Settings page saves 5, the audit timeline shows it, revert
  restores 3, and a staged signal opens 5 entries in the simulator stack.

### Slice 2 — Depth-ordered stage numbers (D2; prerequisite for TP-03)
- `compute_bands`: for BUY, number bands from the top down so stage 2 is the band
  price meets first; same for the direct-zone renumbering at
  `trade_manager.py:910-919`. Band prices are unchanged; only numbers move.
- Check everything that reads stage numbers: `mt5_comment` (`telebot-{sid}-s{n}`,
  only new signals), D-16 (`-s1` only), /staged display, Discord messages.
- Tests: update `compute_bands` unit tests; add a BUY sequence test asserting fill
  order 1→N.
- Done when: a BUY and a SELL sequence both fill stage 2 first and stage N last.

### Slice 3 — Per-stage TP mapping (TP-01..09)
- Storage: `account_settings.stage_tp_map INTEGER[] NOT NULL DEFAULT '{}'`
  (empty = TP2 everywhere) via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`; values
  1–5, length ≤ `max_stages`; added to the field whitelist.
- Model: `AccountSettings.stage_tp_map: tuple[int, ...] = ()`; make the snapshot
  rebuild in `executor.py:1728-1746` tolerate missing keys (TP-07).
- Selection: one helper `tp_for_entry(tps, entry_no, snapshot)` next to
  `_select_target_tp`, reusing its fallback rule. Call it in stage-1 alignment,
  band row creation (correlated and direct-zone), and at-arrival synthetic
  signals. Parser output (`target_tp`) stays as the default.
- Cascade (D3): in `_zone_watch_tick`, compute the nearest TP across the signal's
  rows (and the SL), not the first row seen; cancel all unfilled rows as today.
- UI: SettingsForm gets an "Entry TPs" row of selects; ConfirmDiffDialog shows the
  list; `api/stages.py` + `StagedView.tsx` show each entry's TP (TP-09).
- Tests (new, IDs `TP-0x` in test names): mapping applied on both paths, BUY depth
  order, fallback with fewer TPs, sweep keeps per-row TPs, deterministic cascade
  with mixed TPs, old-snapshot rebuild; update snapshot-dict fixtures listed in
  `tests/test_review_batch*` and `tests/test_staged_*`.
- Done when: the TP-0x tests pass and a simulator run of a 5-entry sell shows
  TP2 on entries 1–3 and TP3 on 4–5 on the positions page.

Order: 1 → 2 → 3. Slice 1 is independent and can ship alone.

## Risks

| Risk | Safe if | Check that could disprove it |
|---|---|---|
| Raising the cap to 5 raises money at risk ~67% per signal (0.12 → 0.2 lot); a full losing sell on the 2 Nov levels goes from ≈ −25.75 to ≈ −37.5 points | Operator accepts it; breakeven only helps after price first moves the right way | Replay of the bot's own history once 5 entries run |
| Overlapping signals on gold share one cap | Cap ≥ entries; dry-run warns when no room is left | Test: second signal while first holds 5 positions → capped, warning shown |
| Renumbering BUY bands confuses rows armed before deploy | Only new signals use the new numbering; old rows keep stored band prices | Test: pre-existing BUY rows still fire at their band |
| Snapshot rebuild fails for old rows | Rebuild uses defaults for missing keys | TP-07 test |
| modify_tp / partial close flatten the per-entry TPs | Accepted per D4/D5 | Documented; revisit with live data |

## Verification

- Backend: `pytest -q` (CI, `.github/workflows/ci.yml`); DB test files run in
  isolated processes (known shared-pool flakiness, `.planning/STATE.md`).
- Frontend: `npm run test`, `npm run lint`, `npm run build` in `frontend/`.
- Real interface: docker-compose dev stack with the MT5 simulator
  (`docker-compose.dev.yml`) — save settings through the SPA, send a sell and a
  buy signal, read the positions and /staged pages. Live MT5 sign-off stays a VPS
  step (deploy-at-end policy).
- Review: one fresh reviewer plus a money/concurrency specialist for slices 2–3
  (cascade and order TPs).

## Progress

- **Slice 1 — implemented 2026-11-20, not committed.** DB CHECK uses 1–100
  (`NOT VALID`, so existing rows never block startup); the form cap is 1–20.
  Revert of a cap change that would break the cross-field rule is refused with
  the reason. Checks: backend `pytest -q` 735 passed / 8 skipped / 1 xfailed
  (Python 3.12, Postgres 16); frontend vitest 20 passed, build green, lint has
  one pre-existing error in `ErrorPanel.tsx`. Not yet exercised: the SPA in a
  browser against a running stack, and the VPS.

## Next action

Slices 2–3. Implementation needs the owner's go-ahead; this plan does not grant it.
