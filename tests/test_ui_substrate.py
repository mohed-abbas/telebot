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

def test_input_css_imports_compat_and_basecoat():
    src = (REPO / "static/css/input.css").read_text()
    assert "@tailwind base" in src
    assert "_compat.css" in src
    assert "basecoat.css" in src

def test_compat_shim_covers_real_v1_class_set():
    """Enumerates the actual class set from base.html:22-40, not CONTEXT D-02's approximation."""
    shim = (REPO / "static/css/_compat.css").read_text()
    for cls in (".card", ".btn", ".btn-red", ".btn-blue", ".btn-green",
                ".profit", ".loss", ".badge-buy", ".badge-sell",
                ".badge-connected", ".badge-disconnected", ".nav-active"):
        assert cls in shim, f"compat shim missing class: {cls}"

def test_htmx_bridge_installed():
    js = (REPO / "static/js/htmx_basecoat_bridge.js").read_text()
    assert "htmx:afterSwap" in js
    assert "basecoat.initAll" in js

def test_dockerfile_has_tailwind_build_stage():
    df = (REPO / "Dockerfile").read_text()
    assert "AS css-build" in df
    assert "v3.4.19" in df, "Tailwind CLI version must be pinned to v3.4.19"
    assert "tailwindcss-linux-x64" in df
    assert "COPY --from=css-build" in df

def test_build_css_script_is_executable_and_produces_hashed_output(tmp_path, monkeypatch):
    """Actually runs build_css.sh locally if tailwindcss is installed.
    Skips cleanly if the CLI isn't present (CI validates this in Docker)."""
    import shutil
    if shutil.which("tailwindcss") is None:
        pytest.skip("tailwindcss CLI not on PATH; Docker build stage exercises this path")

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
