---
phase: 05-foundation
plan: 05
subsystem: ui-substrate-fix
tags: [tailwind-v4, basecoat, gap-closure, uat, docker, operator-docs]

# Dependency graph
requires:
  - phase: 05-foundation plan 02
    provides: v3 css-build stage this plan replaces + vendored Basecoat v0.3.3 + manifest.json pipeline
  - phase: 05-foundation plan 03
    provides: asset_url() helper + base.html cutover consuming the hashed CSS
  - phase: 05-foundation plan 04
    provides: /login (first Basecoat-primitive consumer — proving ground for this fix)
provides:
  - Tailwind v4.2.2 standalone-CLI css-build stage (no Node runtime; arch-aware binary selection)
  - v4-native static/css/input.css (`@import "tailwindcss"` + `@config`)
  - Build-time regression guard in tests/test_ui_substrate.py (markers asserted post-build)
  - Basecoat-working `/login` render (styled card + red `alert-destructive` banner)
  - Operator-doc footgun notes ($→$$ env_file escape, .env.dev migration pointer, 8080 port collision)
affects: [06-staged-entry, 07-dashboard-redesign]

# Tech tracking
tech-stack:
  added: [tailwindcss@v4.2.2 (standalone CLI — replacing v3.4.19)]
  patterns:
    - "TARGETARCH-driven binary selection in multi-arch Docker builds (linux-x64 vs linux-arm64)"
    - "v4 CSS entrypoint via `@import \"tailwindcss\"` + `@config \"...tailwind.config.js\"` bridge (min-churn migration from v3)"
    - "Post-build compiled-CSS marker grep as regression guard (Basecoat + compat-shim invariants)"

key-files:
  created: []
  modified:
    - path: Dockerfile
      purpose: "Bump TAILWIND_VERSION v3.4.19 → v4.2.2. Add TARGETARCH-aware binary selection (amd64→linux-x64, arm64→linux-arm64). Prevents Rosetta/qemu crash (exit 133) on Apple Silicon."
    - path: static/css/input.css
      purpose: "Rewrite v3 `@tailwind base/components/utilities` → v4 single-line `@import \"tailwindcss\"` + `@config \"../../tailwind.config.js\"`. Preserve two trailing @imports (_compat.css, basecoat.css) — v4 resolves these natively; v3 silently dropped them (Gap #1 root cause)."
    - path: tests/test_ui_substrate.py
      purpose: "(a) New regression guard `test_compiled_css_contains_basecoat_and_compat_markers` — post-build grep of hashed CSS for .alert-destructive / .nav-active / .btn-primary; self-skips if CLI absent. (b) Update `test_dockerfile_has_tailwind_build_stage` → asserts `TAILWIND_VERSION=v4`. (c) Update `test_input_css_imports_compat_and_basecoat` → asserts `@import \"tailwindcss\"`."
    - path: .env.example
      purpose: "Two warning blocks above Phase 5 auth: (1) `$`→`$$` env_file interpolation footgun with both fixes documented; (2) .env.dev migration checklist pointing at config.py fail-fast validators."
    - path: docker-compose.dev.yml
      purpose: "Inline comment above `- \"8090:8080\"` mapping explaining 8080 collision (devdock-caddy) + remap pattern."
  groundwork (pre-Task-1 commit):
    - .planning/ROADMAP.md — Phase 5 plan count 4→5 + 05-05 entry
    - .planning/phases/05-foundation/05-CONTEXT.md — add D-04-REVISED
    - .planning/phases/05-foundation/05-05-PLAN.md — plan registration

key-decisions:
  - "Tailwind v4.2.2 chosen (current stable v4 as of 2026-04-19; verified via GitHub releases API `latest` → tag_name=v4.2.2). v4.1.x was the prior cut; v4.2.2 is strictly better for Rust-binary arch coverage."
  - "TARGETARCH-based binary download [Rule 3 auto-fix]: v4's native Rust binary is strict about exec format; linux-x64 under Rosetta on Apple Silicon crashes with 'rosetta error: failed to open elf ...' exit 133. v3.4.19 (older binary) tolerated Rosetta; v4 does not. Dockerfile now selects linux-x64 for amd64 and linux-arm64 for arm64. Both asset names verified against GitHub release v4.2.2 asset list."
  - "v4 migration via `@config` directive instead of migrating tailwind.config.js → CSS `@theme`: keeps the Plan 02 JS config alive (content globs + safelist + dark.{700,800,900} palette) with zero churn. Minimum-surface migration per D-04-REVISED planner-discretion."
  - "scripts/build_css.sh untouched: v4 CLI accepts -i/-o/--minify identically to v3; sha256-prefix + manifest.json emit is pure shell+python and arch-agnostic. Docker build confirmed exit 0 in ~210ms."

patterns-established:
  - "Multi-arch Dockerfile pattern for curl-download binary tools: `ARG TARGETARCH` + `case` statement selecting asset filename. Applies to any future tool similarly distributed (standalone CLI binaries)."
  - "Gap-closure plan type (gap_closure: true): does NOT complete new REQUIREMENTS.md IDs; fixes a regression against requirements a prior plan claimed + shipped broken. Tracked separately from net-new feature plans."

requirements-completed: []
gap-closure: true
uat-gap-closed: ["Gap #1 — compiled CSS missing Basecoat + compat-shim rules"]
uat-tests-promoted: [3, 4]

# Metrics
duration: ~4.5 min (TDD RED → GREEN → docs + end-to-end docker build + curl verification)
completed: 2026-04-19
---

# Phase 5 Plan 05: UI-Substrate Gap Closure Summary

**Bump Tailwind standalone CLI v3.4.19 → v4.2.2, rewrite static/css/input.css with v4 syntax, add post-build marker-grep regression guard, and ship three operator-doc footgun notes — closes UAT Gap #1 (compiled app.css missing Basecoat + compat-shim rules); promotes UAT Tests 3 & 4 to pass.**

## Performance

- **Duration:** ~4.5 min (orient + 1 groundwork commit + RED + GREEN + docs + SUMMARY)
- **Started:** 2026-04-19T18:09:48Z
- **Completed:** 2026-04-19T18:14:18Z
- **Tasks:** 3 (Task 1 TDD RED, Task 2 TDD GREEN, Task 3 docs)
- **TDD gates:** `test(05-05): RED ...` → `feat(05-05): GREEN ...` → `docs(05-05): ...`
- **Files changed:** 5 modified (0 created, 0 removed), +4 groundwork files

## Accomplishments

### Root cause fixed

Plan 02 shipped a css-build stage that silently produced an **11,134-byte** compiled `app.css` containing zero Basecoat rules and zero compat-shim rules. Root cause: Tailwind v3.4.19's standalone CLI does **not** resolve CSS `@import` statements — the two trailing lines in `static/css/input.css` (`@import "./_compat.css"` and `@import "../vendor/basecoat/basecoat.css"`) were dropped without warning. Compounding this, Basecoat v0.3.3 is itself Tailwind-v4-native (uses `@custom-variant`, `@theme`, `has-data-[slot=...]`), so even inlined it would fail v3 parsing. D-04-REVISED lands one move that fixes both: bump the CLI to v4.

### What the v4 bump produces

- Dockerfile ARG `TAILWIND_VERSION=v3.4.19` → **v4.2.2** (current stable; GitHub releases API latest tag_name verified)
- Dockerfile added `ARG TARGETARCH` + case statement selecting `tailwindcss-linux-x64` on amd64 hosts and `tailwindcss-linux-arm64` on arm64 hosts (Apple Silicon)
- `static/css/input.css` rewritten to v4 syntax:
  ```css
  @import "tailwindcss";
  @config "../../tailwind.config.js";

  @import "./_compat.css";
  @import "../vendor/basecoat/basecoat.css";
  ```
- `tailwind.config.js` untouched — v4's `@config` directive consumes the Plan 02 JS config unchanged
- `scripts/build_css.sh` untouched — v4 CLI accepts `-i/-o/--minify` identically

### End-to-end verification (docker compose build + curl against running container)

```
$ docker compose -f docker-compose.dev.yml build telebot --no-cache
… Tailwind v4.2.2 binary downloaded (linux-arm64 on this host)
… build_css.sh exit 0 in ~210ms
… "Built: static/css/app.1181090332ce.css"
… Image telebot-telebot Built

$ curl -s http://localhost:8090/static/css/manifest.json
{
  "app.css": "app.1181090332ce.css"
}

$ HASHED=app.1181090332ce.css
$ curl -s "http://localhost:8090/static/css/$HASHED" | wc -c
144827                          ← 13× the Plan 02 bundle (was 11,134)

$ for m in .alert-destructive .nav-active .btn-primary .card .label .input \
           .btn-red .btn-blue .btn-green .profit .loss .badge-buy .badge-sell; do
    curl -s "http://localhost:8090/static/css/$HASHED" | grep -c "\\${m}"
  done
# All ≥1 — Basecoat primitives (.alert-destructive, .btn-primary, .card, .label,
# .input) AND compat-shim rules (.nav-active, .btn-red/blue/green, .profit,
# .loss, .badge-buy, .badge-sell) now present.
```

### Regression guard

`tests/test_compiled_css_contains_basecoat_and_compat_markers` runs `bash scripts/build_css.sh`, reads the hashed filename from manifest.json, and asserts `.alert-destructive`, `.nav-active`, `.btn-primary` all appear. Self-skips when tailwindcss CLI is absent (Docker build is the enforcing path). Two edited asserts in the existing filesystem-layer tests keep the Dockerfile/input.css surface honest going forward (`TAILWIND_VERSION=v4`, `@import "tailwindcss"`).

### Operator-doc footgun notes

1. **.env.example — `$` → `$$` env_file escape.** Docker-compose interpolates `$` in env_file values and eats most of an argon2 hash. Documented both fixes (double-escape or `environment:` single-quoted).
2. **.env.example — .env.dev migration checklist.** Pointer to drop DASHBOARD_USER/DASHBOARD_PASS and add DASHBOARD_PASS_HASH / SESSION_SECRET / SESSION_COOKIE_SECURE, with reference to config.py fail-fast validators.
3. **docker-compose.dev.yml — 8080 port collision comment.** Explains 8090 host port + remap pattern (8080 collides with devdock-caddy).

## Task Commits

| Gate        | Commit     | Message (truncated)                                                                           |
|-------------|------------|-----------------------------------------------------------------------------------------------|
| Groundwork  | `0889366`  | docs(05-05): register gap-closure plan + D-04-REVISED context + 8090 port remap               |
| Task 1 RED  | `74e0568`  | test(05-05): RED — regression guard for Basecoat + compat-shim markers in compiled CSS (Gap #1) |
| Task 2 GREEN| `03209a0`  | feat(05-05): GREEN — Tailwind v4 standalone CLI + v4 input.css syntax (closes UAT Gap #1)     |
| Task 3 docs | `78ef13f`  | docs(05-05): operator-doc footgun notes — \$→\$\$ escape in env_file, .env.dev migration pointer, 8080 port collision |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking issue] Apple Silicon Docker build crashed on x64 Tailwind v4 binary**

- **Found during:** Task 2 GREEN (`docker compose build telebot --no-cache`)
- **Issue:** The plan's snippet downloads `tailwindcss-linux-x64` unconditionally. On Apple Silicon (Docker Desktop defaults to `arm64/linux` builds), the x64 binary ran under Rosetta/qemu and crashed immediately with `rosetta error: failed to open elf at /lib64/ld-linux-x86-64.so.2` (exit 133). v3.4.19's (older) binary happened to tolerate Rosetta; v4's native Rust binary does not. This blocked the plan's end-to-end acceptance on any arm64 dev machine — and the plan explicitly required the docker build to land.
- **Fix:** Added `ARG TARGETARCH` (auto-populated by BuildKit) + a `case` statement selecting `tailwindcss-linux-x64` on amd64 and `tailwindcss-linux-arm64` on arm64. Both binaries are published for v4.2.2 (verified against GitHub releases API). The x64 asset name string remains in the Dockerfile (as a comment + a case branch) so `tests/test_ui_substrate.py::test_dockerfile_has_tailwind_build_stage` still asserts it.
- **Files modified:** `Dockerfile` (added 11 lines around the curl step)
- **Commit:** `03209a0` (folded into Task 2 GREEN)

### Minor plan-spec drift

None. All three task commits land in the plan's prescribed order with the prescribed messages. The TARGETARCH fix above is a strict addition to the plan's Dockerfile snippet, not a deviation from it.

## Issues Encountered

- Rosetta/qemu trap on v4 x64 binary on Apple Silicon dev daemon — handled as Rule 3 auto-fix above. Clean resolution: TARGETARCH-aware download.
- Nothing else blocking. CLI-dependent tests self-skip locally (no tailwindcss on host); docker build is the enforcing path and confirmed GREEN.

## Threat Register Mitigations (from plan threat model)

| Threat ID    | Disposition | Status                                                                                                           |
|--------------|-------------|------------------------------------------------------------------------------------------------------------------|
| T-5-05-01    | accept      | Source is github.com/tailwindlabs official release (same trust model as Plan 02). Hash-pin deferred to hardening. |
| T-5-05-02    | accept      | .env.example warning is pure text; no secret material. Net security improvement (reduces ad-hoc debug of hash).   |
| T-5-05-03    | accept      | Bundle grew 11 KB → 145 KB minified; gzip over wire ≈15–20 KB. Negligible for single-operator dashboard.          |
| T-5-05-04    | mitigate    | .env.example warning text explicitly uses single quotes (`'$argon2id…'`) in the `environment:` alternative.       |

## Known Stubs / Phase 7 Follow-Ups

- **login.html `<div class="card-header">` / `<div class="card-body">` do NOT render as Basecoat cards.** Basecoat v0.3.3 defines `.card > header` / `.card > section` / `.card > footer` (semantic children), not `.card-header` / `.card-body` classes. The login template's div-wrappers remain unstyled boxes inside the styled `.card` container. This is **pre-existing** and was already documented as a Phase 7 follow-up in `05-04-SUMMARY.md` ("Login visual polish: migrate to semantic children"). It is independent of Gap #1 — the bundle now correctly contains every selector Basecoat defines; the template just doesn't use the semantic markup. The styled `.card` shell + `.label` + `.input` + `.btn-primary` + `.alert-destructive` render correctly.
- No other stubs introduced by this plan.

## Verification Results

### Filesystem-layer tests (Postgres-free, CLI-independent)

```
$ .venv/bin/python -m pytest tests/test_ui_substrate.py -v
7 passed, 3 skipped
```

The 3 skips are CLI-dependent tests that self-skip when `tailwindcss` is not on the host PATH (by design — the Docker css-build stage is the enforcing path for those invariants). Docker build verified those invariants end-to-end.

### Plan-spec grep acceptance (Task 3)

```
$ grep -c 'DASHBOARD_PASS_HASH' .env.example                                           → 4 (≥1)
$ grep -cE '(\$\$|interpolat|escape)' .env.example                                     → 4 (≥1)
$ grep -ciE 'env\.dev' .env.example                                                    → 2 (≥1)
$ grep -c '8090:8080' docker-compose.dev.yml                                           → 1 (=1)
$ grep -cE '^[[:space:]]*#.*(8080|devdock|collision|port)' docker-compose.dev.yml      → 4 (≥1)
```

### End-to-end acceptance (docker stack up + curl)

```
$ curl -s "http://localhost:8090/static/css/app.1181090332ce.css" | wc -c   → 144827  (≥30000 ✓)
$ curl -s "http://localhost:8090/static/css/app.1181090332ce.css" | grep -c .alert-destructive  → 1 (≥1 ✓)
$ curl -s "http://localhost:8090/static/css/app.1181090332ce.css" | grep -c .nav-active         → 1 (≥1 ✓)
$ curl -s "http://localhost:8090/static/css/app.1181090332ce.css" | grep -c .btn-primary        → 1 (≥1 ✓)
$ curl -s -o /dev/null -w "%{http_code}" http://localhost:8090/login                            → 200 ✓
```

## User Setup Required

None code-side — the bump is pure build tooling. Operators redeploying v1.1 after this patch only need to rebuild the image:

```bash
docker compose -f docker-compose.dev.yml build telebot --no-cache
docker compose -f docker-compose.dev.yml up -d telebot
```

On arm64 hosts the TARGETARCH-aware fetch is automatic; on amd64 CI the linux-x64 binary is downloaded (same as v3 pattern).

## Self-Check: PASSED

Verified on disk + against running container:

- [x] `Dockerfile` contains `TAILWIND_VERSION=v4.2.2` + both `tailwindcss-linux-x64` and `tailwindcss-linux-arm64` asset name strings (TARGETARCH case branches)
- [x] `static/css/input.css` contains `@import "tailwindcss"` and `@config "../../tailwind.config.js"`
- [x] `tests/test_ui_substrate.py` contains `test_compiled_css_contains_basecoat_and_compat_markers` function + the two updated asserts
- [x] `.env.example` contains the `$$` escape warning + `.env.dev` migration pointer
- [x] `docker-compose.dev.yml` contains inline port-collision comment above `8090:8080` mapping
- [x] `.planning/phases/05-foundation/05-05-PLAN.md` committed (no longer untracked)
- [x] Commits verified in `git log`: `0889366` (groundwork), `74e0568` (RED), `03209a0` (GREEN), `78ef13f` (docs)
- [x] docker image built successfully (telebot-telebot:latest, exit 0)
- [x] Compiled CSS = 144,827 bytes (vs Plan 02's 11,134 — 13×)
- [x] Served CSS grep counts: `.alert-destructive=1, .nav-active=1, .btn-primary=1` all ≥1
- [x] `/login` returns HTTP 200 with `<link rel="stylesheet" href="/static/css/app.1181090332ce.css">`

## TDD Gate Compliance

- RED gate present: `test(05-05): RED …` (`74e0568`) — both edited asserts confirmed failing before Task 2 landed.
- GREEN gate present: `feat(05-05): GREEN …` (`03209a0`) — both RED tests flipped to green + end-to-end docker build confirmed marker-bearing bundle.
- REFACTOR gate: not needed (clean one-step bump; no interim cruft to fold).
- Order enforced: groundwork → RED → GREEN → docs (matches plan's prescribed sequence).

---
*Phase: 05-foundation*
*Plan: 05 (gap closure)*
*Completed: 2026-04-19*
