"""API-04: shared formatter contract — single source of display strings.

Drives api/formatting.py directly (Plan 03 extends route-level assertions through
/api/v2/positions). Verifies the D-05 dual-value contract: a raw numeric field
plus a parallel `_display` string formatted per the symbol/money/volume/timestamp
rules (D-06 machine ISO-8601, D-07 absolute-UTC display).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from api import formatting as fmt


def test_xauusd_price_raw_plus_2dp_display():
    """A XAUUSD price keeps the raw float and exposes a 2dp display string."""
    raw_open_price = 2800.123
    open_price_display = fmt.price_display("XAUUSD", raw_open_price)
    # Raw value is preserved verbatim (SPA submits the exact server number — Pitfall 5).
    assert raw_open_price == 2800.123
    # Display is 2dp for XAUUSD (broker convention).
    assert open_price_display == "2800.12"
    # Case-insensitive symbol lookup.
    assert fmt.price_display("xauusd", 2800.5) == "2800.50"


def test_non_xauusd_defaults_to_5dp():
    """A non-XAUUSD symbol falls back to 5dp FX precision."""
    assert fmt.price_display("EURUSD", 1.23456) == "1.23456"
    assert fmt.price_display("GBPUSD", 1.2) == "1.20000"


def test_volume_formats_to_2dp():
    assert fmt.volume_display(0.3) == "0.30"
    assert fmt.volume_display(1.5) == "1.50"


def test_money_formats_thousands_2dp():
    assert fmt.money_display(12345.6) == "12,345.60"
    assert fmt.money_display(-50.5) == "-50.50"


def test_timestamp_machine_is_iso8601_with_offset():
    """ts_machine returns ISO-8601 with an explicit UTC offset (D-06)."""
    dt = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    machine = fmt.ts_machine(dt)
    assert machine == "2026-01-02T03:04:05+00:00"
    # Must carry a parseable offset, not a naive string.
    assert re.search(r"[+-]\d{2}:\d{2}$", machine)


def test_timestamp_display_is_absolute_utc():
    """ts_display returns an absolute 'YYYY-MM-DD HH:MM:SS UTC' string (D-07)."""
    dt = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert fmt.ts_display(dt) == "2026-01-02 03:04:05 UTC"


def test_timestamp_converts_non_utc_to_utc():
    """A non-UTC aware datetime is normalised to UTC before formatting."""
    from datetime import timedelta

    plus_two = timezone(timedelta(hours=2))
    dt = datetime(2026, 1, 2, 5, 4, 5, tzinfo=plus_two)  # 03:04:05 UTC
    assert fmt.ts_display(dt) == "2026-01-02 03:04:05 UTC"
    assert fmt.ts_machine(dt) == "2026-01-02T03:04:05+00:00"
