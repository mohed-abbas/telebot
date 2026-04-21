"""UI substrate — filesystem + build-artifact checks (no DB needed)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def test_basecoat_vendored():
    css = REPO / "static/vendor/basecoat/basecoat.css"
    js = REPO / "static/vendor/basecoat/basecoat.min.js"
    assert css.is_file() and css.stat().st_size > 10_000
    assert js.is_file() and js.stat().st_size > 10_000
    assert "initAll" in js.read_text(errors="ignore")

def test_drizzle_config_removed():
    assert not (REPO / "drizzle.config.json").exists(), "D-09: delete stray config"

def test_tailwind_content_glob_includes_python():
    cfg = (REPO / "tailwind.config.js").read_text()
    assert "./**/*.py" in cfg, "D-05 / Pitfall 10: content glob must include Python files"
    assert "darkMode" in cfg

def test_input_css_imports_basecoat():
    src = (REPO / "static/css/input.css").read_text()
    assert '@import "tailwindcss"' in src, (
        "v4 entrypoint must use @import (Gap #1 / D-04-REVISED)"
    )
    assert "basecoat.css" in src
    assert ".sidebar-link" in src, "Phase 7 sidebar link styles must be in input.css"

def test_htmx_bridge_installed():
    js = (REPO / "static/js/htmx_basecoat_bridge.js").read_text()
    assert "htmx:afterSwap" in js
    assert "basecoat.initAll" in js

def test_dockerfile_has_tailwind_build_stage():
    df = (REPO / "Dockerfile").read_text()
    assert "AS css-build" in df
    assert "TAILWIND_VERSION=v4" in df, (
        "Tailwind CLI must be v4+ (Basecoat v0.3.3 is v4-native — Gap #1)"
    )
    assert "tailwindcss-linux-x64" in df
    assert "COPY --from=css-build" in df

def test_build_css_script_is_executable_and_produces_hashed_output(tmp_path, monkeypatch):
    """Actually runs build_css.sh locally if tailwindcss is installed.
    Skips cleanly if the CLI isn't present (CI validates this in Docker)."""
    import shutil
    for tool in ("tailwindcss", "sha256sum", "bash", "python3"):
        if shutil.which(tool) is None:
            pytest.skip(
                f"{tool!r} not on PATH; Docker css-build stage enforces this "
                "regression check (see Gap #1 / D-04-REVISED)"
            )

    # Run in repo root (deterministic output test — Pitfall 11)
    r1 = subprocess.run(["bash", "scripts/build_css.sh"], cwd=REPO, capture_output=True)
    assert r1.returncode == 0, r1.stderr.decode()
    manifest = json.loads((REPO / "static/css/manifest.json").read_text())
    hashed = manifest["app.css"]
    assert hashed.startswith("app.") and hashed.endswith(".css")
    first_hash = hashed

    # Second build against identical input must produce the identical hash
    r2 = subprocess.run(["bash", "scripts/build_css.sh"], cwd=REPO, capture_output=True)
    assert r2.returncode == 0
    manifest2 = json.loads((REPO / "static/css/manifest.json").read_text())
    assert manifest2["app.css"] == first_hash, (
        "Pitfall 11: identical input must produce identical hash"
    )

    # UI-03: Python-inlined classes survive the purge
    css_file = REPO / "static/css" / first_hash
    content = css_file.read_text()
    assert "text-green-400" in content, "UI-03: dashboard.py inline class was purged"
    assert "text-red-400" in content, "UI-03: dashboard.py inline class was purged"

def test_manifest_schema_when_present(tmp_path):
    """If a manifest exists (post-build), it has the expected shape."""
    manifest_path = REPO / "static/css/manifest.json"
    if not manifest_path.exists():
        pytest.skip("No build artifact present; covered by the build-invocation test")
    m = json.loads(manifest_path.read_text())
    assert "app.css" in m
    assert m["app.css"].startswith("app.") and m["app.css"].endswith(".css")


def test_compiled_css_contains_basecoat_markers():
    """Gap #1 regression guard — compiled app.<hash>.css MUST contain
    Basecoat primitives (proves `@import "../vendor/basecoat/basecoat.css"`
    was resolved by Tailwind) AND Phase 7 custom styles (proves input.css
    custom rules are included).

    Self-skips if `tailwindcss` CLI is not on PATH — the Docker css-build
    stage is the enforcing path in that case. The Gap #1 UAT failure manifests
    as this test failing (v3 CLI silently drops @import statements; v4 resolves them).
    """
    import shutil
    for tool in ("tailwindcss", "sha256sum", "bash", "python3"):
        if shutil.which(tool) is None:
            pytest.skip(
                f"{tool!r} not on PATH; Docker css-build stage enforces this "
                "regression check (see Gap #1 / D-04-REVISED)"
            )

    r = subprocess.run(["bash", "scripts/build_css.sh"], cwd=REPO, capture_output=True)
    assert r.returncode == 0, r.stderr.decode()

    manifest = json.loads((REPO / "static/css/manifest.json").read_text())
    hashed = manifest["app.css"]
    compiled = (REPO / "static/css" / hashed).read_text()

    fix_hint = (
        "Gap #1 regression — check Dockerfile TAILWIND_VERSION (must be v4+) "
        'and static/css/input.css @import syntax (must be `@import "tailwindcss";`). '
        "v3.4.19 CLI silently drops CSS @import statements; v4 resolves them natively."
    )
    assert ".alert-destructive" in compiled, (
        f"Basecoat primitive missing from compiled CSS (source: "
        f"static/vendor/basecoat/basecoat.css). {fix_hint}"
    )
    assert ".sidebar-link" in compiled, (
        f"Phase 7 sidebar styles missing from compiled CSS (source: "
        f"static/css/input.css). {fix_hint}"
    )
    assert ".btn-primary" in compiled, (
        f"Basecoat button primitive missing from compiled CSS (source: "
        f"static/vendor/basecoat/basecoat.css). {fix_hint}"
    )
