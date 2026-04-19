"""Config loader contract — fail-fast when misconfigured (D-15, D-20/D-21, Pitfall 5)."""
from __future__ import annotations

import importlib
import os
import sys

import pytest


def _reload_config(env: dict[str, str]):
    """Re-import config with a scoped env. SystemExit is the expected outcome for many cases."""
    # Preserve everything required for a clean baseline
    baseline = {
        "TG_API_ID": "1", "TG_API_HASH": "x", "TG_SESSION": "x", "TG_CHAT_IDS": "-1",
        "DISCORD_WEBHOOK_URL": "https://example", "TIMEZONE": "UTC",
        "DATABASE_URL": "postgresql://u:p@h:5432/d",
        "DASHBOARD_PASS_HASH": "$argon2id$v=19$m=65536,t=3,p=4$" + "a" * 32 + "$" + "b" * 32,
        "SESSION_SECRET": "A" * 48,  # 48 chars ≥ 32 bytes
    }
    merged = {**baseline, **env}
    # Purge conflicting vars
    for key in list(os.environ):
        if key in baseline or key in env or key in (
            "DASHBOARD_USER", "DASHBOARD_PASS",
        ):
            os.environ.pop(key, None)
    os.environ.update(merged)
    sys.modules.pop("config", None)
    return importlib.import_module("config")


def test_session_secret_missing_raises():
    with pytest.raises(SystemExit, match="SESSION_SECRET"):
        _reload_config({"SESSION_SECRET": ""})


def test_session_secret_too_weak_raises():
    # 16 ascii chars = 16 bytes — fails ≥32 byte check
    with pytest.raises(SystemExit, match="bytes of entropy"):
        _reload_config({"SESSION_SECRET": "x" * 16})


def test_session_secret_valid_loads():
    cfg = _reload_config({"SESSION_SECRET": "A" * 48})
    assert len(cfg.settings.session_secret.encode()) >= 32


def test_plaintext_dashboard_pass_refuses_boot():
    # D-21: hard cutover
    with pytest.raises(SystemExit, match="DASHBOARD_PASS plaintext"):
        _reload_config({"DASHBOARD_PASS": "anyvalue"})


def test_missing_dashboard_hash_refuses_boot():
    with pytest.raises(SystemExit, match="DASHBOARD_PASS_HASH"):
        _reload_config({"DASHBOARD_PASS_HASH": ""})


def test_dashboard_user_silently_ignored():
    # D-22: DASHBOARD_USER must NOT cause startup failure
    cfg = _reload_config({"DASHBOARD_USER": "legacy-admin"})
    assert not hasattr(cfg.settings, "dashboard_user")


def test_session_cookie_secure_defaults_true():
    cfg = _reload_config({})
    assert cfg.settings.session_cookie_secure is True


def test_session_cookie_secure_override_false():
    cfg = _reload_config({"SESSION_COOKIE_SECURE": "false"})
    assert cfg.settings.session_cookie_secure is False
