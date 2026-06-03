"""Bot-core untouchability gate (Phase 08, every wave merge depends on this).

The v1.2 JSON API refactor confines its blast radius to the presentation layer:
the four bot-core files and the MT5 REST bridge must be called only, never edited.
This test mechanizes that invariant — `git diff --exit-code` over those paths must
be empty. Run before every wave merge.

Named with a leading underscore so pytest's default collection still picks it up
(it does — collection is by `test_*`/`*_test` for functions, file glob is
`test_*.py` by default, so this file is invoked explicitly in the plan's verify
command: `pytest tests/_bot_core_diff_guard.py -x`).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

# Repo root (parent of tests/).
_REPO_ROOT = Path(__file__).resolve().parent.parent

_BOT_CORE_PATHS = [
    "executor.py",
    "trade_manager.py",
    "db.py",
    "mt5_connector.py",
    "mt5-rest-server/",
]


def test_bot_core_unmodified():
    """git diff of the four bot-core files + mt5-rest-server/ must be empty."""
    # Only assert against paths that actually exist in this checkout (mt5-rest-server/
    # may be absent in some worktrees); a missing path is not a violation.
    paths = [p for p in _BOT_CORE_PATHS if (_REPO_ROOT / p).exists()]
    if not paths:
        pytest.skip("No bot-core paths present in this checkout")

    result = subprocess.run(
        ["git", "diff", "--exit-code", "--", *paths],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "Bot core / MT5 bridge was modified — this is forbidden in v1.2.\n"
        f"Offending diff:\n{result.stdout}"
    )
