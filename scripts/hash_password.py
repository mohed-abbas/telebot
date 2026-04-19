#!/usr/bin/env python3
"""Generate DASHBOARD_PASS_HASH env var value. Usage: python scripts/hash_password.py"""
from __future__ import annotations

import getpass
import sys

from argon2 import PasswordHasher


def main() -> int:
    pw = getpass.getpass("New dashboard password: ")
    pw2 = getpass.getpass("Confirm: ")
    if pw != pw2:
        print("Passwords do not match.", file=sys.stderr)
        return 1
    if len(pw) < 12:
        print("Password must be at least 12 characters.", file=sys.stderr)
        return 2
    ph = PasswordHasher()
    print(f"DASHBOARD_PASS_HASH={ph.hash(pw)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
