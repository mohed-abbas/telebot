---
phase: 05
fixed_at: 2026-04-19T18:35:00Z
source_review: 05-REVIEW.md
scope: default (blocker+high+medium)
findings_fixed: 1
findings_skipped: 5
status: all_fixed
---

# Phase 05 — Code Review Fix Report (Plan 05-05 Gap-Closure)

**Fixed at:** 2026-04-19T18:35:00Z
**Source review:** `.planning/phases/05-foundation/05-REVIEW.md`
**Scope:** default filter — BLOCKER + HIGH + MEDIUM only (LOW and INFO excluded)

**Summary:**
- Findings in scope: 1 (1 MEDIUM)
- Fixed: 1
- Skipped (out-of-scope): 5 (3 LOW, 2 INFO)

---

## Fixed Issues

### MD-01 — `test_compiled_css_contains_basecoat_and_compat_markers` assumes GNU `sha256sum` on PATH

**Files modified:** `tests/test_ui_substrate.py`
**Lines changed:** 61–67 (sibling `test_build_css_script_is_executable_and_produces_hashed_output`) + 111–117 (the new Gap #1 regression test)
**Commit:** `df1cf7d`

**Applied fix:**
Replaced the single-binary skip guard (`shutil.which("tailwindcss")`) in both tests with a loop that checks all four binaries that `scripts/build_css.sh` depends on: `tailwindcss`, `sha256sum`, `bash`, and `python3`. If any one is missing, the test skips cleanly with a specific message naming the missing binary.

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

**Why both tests (not just the new one):** REVIEW.md:60 explicitly notes the sibling test at line 58 has the same latent issue and calls for them to be fixed together. Applied the same broadened guard to both so a macOS dev box with `tailwindcss` but no `coreutils` (no `sha256sum`) now gets a clear skip message instead of a confusing mid-run `sha256sum: command not found` that looks like a Gap #1 regression.

**Verification performed:**
1. Tier 1 — Re-read modified regions (lines 58–67 and 101–117) to confirm the loop is present in both tests and surrounding code is intact.
2. Tier 2 — `python3 -c "import ast; ast.parse(...)"` on the modified file returned `OK` (syntax valid).
3. Functional — `.venv/bin/pytest tests/test_ui_substrate.py -x --collect-only` still collects all 10 tests including both modified ones.
4. Functional — `.venv/bin/pytest tests/test_ui_substrate.py -x` on this machine (which has no `tailwindcss` on PATH) reports `7 passed, 3 skipped in 0.01s`. Both build-css tests skip cleanly at the new guard, same as before. Present-machine behaviour unchanged.

---

## Skipped Issues (out-of-scope for default filter)

### LO-01 — Test mutates repo state under `static/css/` with no teardown
- **Severity:** LOW
- **Reason for skip:** Out of scope — default filter includes only BLOCKER + HIGH + MEDIUM. Reviewer also marked this as consistent with pre-existing pattern (not a regression introduced by 05-05) and optional.

### LO-02 — `.env.example` placeholder `DASHBOARD_PASS_HASH` contains unescaped `$` chars below the escape-warning block
- **Severity:** LOW
- **Reason for skip:** Out of scope — default filter excludes LOW.

### LO-03 — `docker-compose.dev.yml` inline comment nudges operator to edit tracked YAML to resolve port collision
- **Severity:** LOW
- **Reason for skip:** Out of scope — default filter excludes LOW.

### IN-01 — Dockerfile `case` handles unsupported arches with a plain `exit 1`
- **Severity:** INFO
- **Reason for skip:** Out of scope — default filter excludes INFO. Reviewer explicitly marked "no action needed, correct pattern."

### IN-02 — `test_dockerfile_has_tailwind_build_stage` substring check accepts pre-release v4 tags
- **Severity:** INFO
- **Reason for skip:** Out of scope — default filter excludes INFO. Reviewer explicitly marked "no action required, substring looseness is intentional."

---

_Fixed: 2026-04-19T18:35:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
