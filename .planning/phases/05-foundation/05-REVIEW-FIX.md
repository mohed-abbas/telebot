---
phase: 05
fixed_at: 2026-04-19T19:05:00Z
source_review: 05-REVIEW.md
scope: --all
findings_fixed: 3
findings_skipped: 3
status: all_fixed
---

# Phase 05 — Code Review Fix Report (Plan 05-05 Gap-Closure)

**Fixed at:** 2026-04-19T19:05:00Z
**Source review:** `.planning/phases/05-foundation/05-REVIEW.md`
**Scope:** `--all` — covers BLOCKER + HIGH + MEDIUM + LOW + INFO
**Iteration:** 2 (follow-up pass extending the initial MEDIUM-only fix from 2026-04-19T18:35:00Z)

**Summary:**
- Findings in scope: 6 (1 MEDIUM, 3 LOW, 2 INFO)
- Fixed: 3 (MD-01 prior + LO-02 + LO-03)
- Skipped: 3 (LO-01, IN-01, IN-02 — all explicit "no action" or "deferred" per reviewer)

---

## Fixed Issues

### MD-01 — `test_compiled_css_contains_basecoat_and_compat_markers` assumes GNU `sha256sum` on PATH

- **Severity:** MEDIUM
- **File:** `tests/test_ui_substrate.py:114` (new test) + `:58` (sibling test)
- **Status:** fixed-prior
- **Commit:** `df1cf7d`
- **Applied fix:** Replaced the single-binary skip guard (`shutil.which("tailwindcss")`) in both tests with a loop that checks all four binaries `scripts/build_css.sh` depends on: `tailwindcss`, `sha256sum`, `bash`, `python3`. If any is missing, the test skips cleanly with a specific message naming the missing binary. Applied to both the new Gap #1 regression test and the pre-existing sibling test per REVIEW.md:60.

Full detail (before/after, verification) is preserved in the iteration-1 report section below for historical reference.

**Before:**
```python
if shutil.which("tailwindcss") is None:
    pytest.skip("tailwindcss CLI not on PATH; Docker build stage exercises this path")
```

**After:**
```python
for tool in ("tailwindcss", "sha256sum", "bash", "python3"):
    if shutil.which(tool) is None:
        pytest.skip(
            f"{tool!r} not on PATH; Docker css-build stage enforces this "
            "regression check (see Gap #1 / D-04-REVISED)"
        )
```

**Verification (iteration 1):**
1. Tier 1 — re-read lines 58–67 and 101–117, confirmed loop present in both tests, surrounding code intact.
2. Tier 2 — `python3 -c "import ast; ast.parse(...)"` returned OK.
3. Functional — `pytest tests/test_ui_substrate.py -x --collect-only` still collects all 10 tests.
4. Functional — `pytest tests/test_ui_substrate.py -x` on a machine without `tailwindcss` reports `7 passed, 3 skipped`; both build-css tests skip cleanly at the new guard.

---

### LO-02 — `.env.example` placeholder `DASHBOARD_PASS_HASH` reintroduces the `$` footgun directly below the escape-warning block

- **Severity:** LOW
- **File:** `.env.example:80`
- **Status:** fixed-now
- **Commit:** `fa8027d`
- **Files modified:** `.env.example`

**Applied fix:** Added an inline placement-specific reminder directly above the `DASHBOARD_PASS_HASH=...` placeholder (option (b) from REVIEW.md:108-112), so a copy-paste-oriented operator sees the "double every `$` OR move to `environment:` block" instruction at the exact moment they are about to overwrite the placeholder with a real hash. Did NOT remove the existing Lines 61–70 warning block — both stay (the earlier block explains *why*; the new reminder says *here, now*).

```diff
 # Generate hash with: python scripts/hash_password.py
+# ⚠ When pasting the real hash on the line below, either double every `$` (fix (a) above)
+# or move the variable to compose's `environment:` block with single quotes (fix (b)).
 DASHBOARD_PASS_HASH=$argon2id$v=19$m=65536,t=3,p=4$...
```

Also added a `# DASHBOARD_HOST_PORT=8090` doc line in the `── Dashboard ──` block (supports the LO-03 fix below):

```diff
 # ── Dashboard ──
 DASHBOARD_ENABLED=true
 DASHBOARD_PORT=8080
+
+# Host-side port for the dev compose stack. Defaults to 8090 because 8080 often
+# collides with devdock-caddy. Override in .env.dev if 8090 is also in use.
+# DASHBOARD_HOST_PORT=8090
```

**Verification performed:**
- `grep -n "When pasting the real hash" .env.example` → line 84 (1 match).
- `grep -n "DASHBOARD_HOST_PORT" .env.example` → line 62 (1 match — the new override doc line).

---

### LO-03 — `docker-compose.dev.yml` inline comment nudges operator to edit tracked YAML to resolve port collision

- **Severity:** LOW
- **File:** `docker-compose.dev.yml:37-41`
- **Status:** fixed-now
- **Commit:** `fa8027d`
- **Files modified:** `docker-compose.dev.yml` (+ `.env.example` doc line, co-committed with LO-02)

**Applied fix:** Replaced the hard-coded `"8090:8080"` mapping + 4-line operator comment with compose interpolation `"${DASHBOARD_HOST_PORT:-8090}:8080"` plus a tightened 2-line comment. A host with a pre-existing 8090 collision can now set `DASHBOARD_HOST_PORT=8091` in `.env.dev` without touching the tracked compose file — the old "remap to any free port (e.g. '8091:8080')" instruction is now obsolete because the parametrization solves the problem cleanly.

```diff
     ports:
-      # Host port 8090 because 8080 commonly collides with devdock-caddy or
-      # other dev reverse proxies on shared dev machines. 8080 inside the
-      # container is fixed (DASHBOARD_PORT=8080). If 8090 is also in use
-      # on your host, remap to any free port (e.g. "8091:8080").
-      - "8090:8080"
+      # Host port defaults to 8090 because 8080 collides with devdock-caddy.
+      # Override per host by setting DASHBOARD_HOST_PORT in .env.dev.
+      - "${DASHBOARD_HOST_PORT:-8090}:8080"
```

**Verification performed:**
- `grep 'DASHBOARD_HOST_PORT:-8090' docker-compose.dev.yml` → 1 match (line 39).
- `python3 -c "import yaml; yaml.safe_load(open('docker-compose.dev.yml'))"` → no exception (using project venv, which has PyYAML).
- `docker compose -f docker-compose.dev.yml config` parses without errors and emits `published: "8090"` for the telebot service (verifying the `${DASHBOARD_HOST_PORT:-8090}` default resolves correctly when the env var is unset). Exit code 0.

---

## Skipped Issues

### LO-01 — Test mutates repo state under `static/css/` with no teardown

- **Severity:** LOW
- **File:** `tests/test_ui_substrate.py:114-119`
- **Status:** skipped-deferred
- **Reason for skip:** Reviewer explicitly deferred this in REVIEW.md:88: *"Deferred — the pre-existing pattern makes this test-suite-wide, not test-specific."* Fixing inside this phase would touch a suite-wide pattern (both the new test and the pre-existing sibling at line 58 write artifacts into the live tree) and belongs in a dedicated test-hygiene refactor, not here.
- **Original issue:** Running `pytest tests/test_ui_substrate.py` writes `static/css/app.*.css` and `static/css/manifest.json` into the live working tree instead of a `tmp_path` copy.

### IN-01 — Dockerfile `case` handles unsupported arches with plain `exit 1`

- **Severity:** INFO
- **File:** `Dockerfile:17-21`
- **Status:** skipped-no-action
- **Reason for skip:** Reviewer explicitly wrote in REVIEW.md:158: *"Fix: None — this is the correct pattern."* The finding was informational only, flagged for build-ergonomics awareness. No change intended.
- **Original issue:** The unsupported-TARGETARCH error path logs the bad value and exits — already better than most release Dockerfiles. No improvement identified.

### IN-02 — `test_dockerfile_has_tailwind_build_stage` substring check accepts pre-release v4 tags

- **Severity:** INFO
- **File:** `tests/test_ui_substrate.py:52`
- **Status:** skipped-no-action
- **Reason for skip:** Reviewer explicitly wrote in REVIEW.md:174: *"Fix: None required."* The substring looseness is *intentional* — it matches the "Basecoat v0.3.3 is v4-native" constraint rather than pinning a specific patch release. Current value `v4.2.2` satisfies the check.
- **Original issue:** `"TAILWIND_VERSION=v4" in df` would also match `v4.0.0-alpha.1` or `v40.0.0`. Intentional looseness; upgrade-path regex noted for future reference if pinning is later desired.

---

_Fixed: 2026-04-19T19:05:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 2 (follow-up `--all` pass; iteration 1 fixed MD-01 on 2026-04-19T18:35:00Z in commit df1cf7d)_
