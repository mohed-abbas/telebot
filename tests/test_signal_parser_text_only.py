"""Tests for Phase 6 D-01/D-02 — text-only "now" signals ("Gold buy now", "XAU sell now").

RED baseline: all 5 tests fail until Task 2 adds SignalType.OPEN_TEXT_ONLY and
the _RE_OPEN_TEXT_ONLY recognizer.
"""
from signal_parser import parse_signal
from models import SignalType, Direction


class TestOpenTextOnly:
    def test_text_only_buy_parses(self):
        s = parse_signal("Gold buy now")
        assert s is not None
        assert s.type == SignalType.OPEN_TEXT_ONLY
        assert s.symbol == "XAUUSD"
        assert s.direction == Direction.BUY
        assert s.entry_zone is None
        assert s.sl is None
        assert s.tps == []

    def test_text_only_sell_parses(self):
        s = parse_signal("XAU sell now")
        assert s is not None
        assert s.type == SignalType.OPEN_TEXT_ONLY
        assert s.direction == Direction.SELL

    def test_text_only_with_numbers_rejects_to_OPEN(self):
        # "Gold sell now 4978 - 4982" must still hit _RE_OPEN and produce OPEN (zone)
        s = parse_signal("Gold sell now 4978 - 4982\nSL: 4986\nTP: 4975")
        assert s is not None
        assert s.type == SignalType.OPEN  # not OPEN_TEXT_ONLY

    def test_text_only_case_insensitive(self):
        assert parse_signal("GOLD BUY NOW") is not None
        assert parse_signal("gold Buy Now") is not None

    def test_now_without_symbol_returns_none(self):
        assert parse_signal("buy now") is None  # no symbol
