"""Tests for signal_parser — 30+ signal variations."""

import pytest

from models import Direction, SignalType
from signal_parser import parse_signal, format_parsed_signal


# ═══════════════════════════════════════════════════════════════════════
# NEW TRADE SIGNALS — ZONE ENTRY
# ═══════════════════════════════════════════════════════════════════════


class TestOpenSignalsZone:
    def test_sell_zone_with_multiple_tps(self):
        text = (
            "Gold sell now 4978 - 4982\n\n"
            "SL: 4986\n\n"
            "TP. 4975\n"
            "TP: 4973\n"
            "TP: 4971\n"
            "TP: 4969\n"
            "TP: open"
        )
        s = parse_signal(text)
        assert s is not None
        assert s.type == SignalType.OPEN
        assert s.symbol == "XAUUSD"
        assert s.direction == Direction.SELL
        assert s.entry_zone == (4978.0, 4982.0)
        assert s.sl == 4986.0
        assert len(s.tps) == 5
        assert s.tps[0] == 4975.0
        assert s.tps[1] == 4973.0
        assert s.tps[4] == "open"
        assert s.target_tp == 4973.0  # TP2

    def test_buy_zone(self):
        text = (
            "Gold buy now 2140 - 2145\n"
            "SL: 2135\n"
            "TP: 2150\n"
            "TP: 2155\n"
            "TP: 2160"
        )
        s = parse_signal(text)
        assert s is not None
        assert s.type == SignalType.OPEN
        assert s.direction == Direction.BUY
        assert s.entry_zone == (2140.0, 2145.0)
        assert s.sl == 2135.0
        assert s.target_tp == 2155.0  # TP2

    def test_zone_reversed_prices(self):
        """Zone prices in wrong order should still normalize."""
        text = "Gold sell now 4982 - 4978\nSL: 4986\nTP: 4975\nTP: 4973"
        s = parse_signal(text)
        assert s is not None
        assert s.entry_zone == (4978.0, 4982.0)

    def test_zone_with_dash_variants(self):
        """Test different dash types: - – —"""
        for dash in ["-", "–", "—"]:
            text = f"Gold sell now 4978 {dash} 4982\nSL: 4986\nTP: 4975\nTP: 4973"
            s = parse_signal(text)
            assert s is not None, f"Failed with dash: {dash!r}"
            assert s.entry_zone == (4978.0, 4982.0)

    def test_zone_no_space_around_dash(self):
        text = "Gold sell now 4978-4982\nSL: 4986\nTP: 4975\nTP: 4973"
        s = parse_signal(text)
        assert s is not None
        assert s.entry_zone == (4978.0, 4982.0)

    def test_xauusd_symbol_variant(self):
        text = "XAUUSD buy now 2140 - 2145\nSL: 2135\nTP: 2150\nTP: 2155"
        s = parse_signal(text)
        assert s is not None
        assert s.symbol == "XAUUSD"
        assert s.direction == Direction.BUY

    def test_xau_usd_slash_variant(self):
        text = "XAU/USD sell now 4978 - 4982\nSL: 4986\nTP: 4975\nTP: 4973"
        s = parse_signal(text)
        assert s is not None
        assert s.symbol == "XAUUSD"

    def test_decimal_prices(self):
        text = "Gold sell now 4978.50 - 4982.30\nSL: 4986.00\nTP: 4975.50\nTP: 4973.20"
        s = parse_signal(text)
        assert s is not None
        assert s.entry_zone == (4978.50, 4982.30)
        assert s.sl == 4986.0
        assert s.tps[0] == 4975.50

    def test_only_one_tp(self):
        text = "Gold sell now 4978 - 4982\nSL: 4986\nTP: 4975"
        s = parse_signal(text)
        assert s is not None
        assert len(s.tps) == 1
        assert s.target_tp == 4975.0  # fallback to last

    def test_tp_dot_separator(self):
        """TP. vs TP: should both work."""
        text = "Gold sell now 4978 - 4982\nSL: 4986\nTP. 4975\nTP. 4973"
        s = parse_signal(text)
        assert s is not None
        assert s.tps == [4975.0, 4973.0]

    def test_no_sl(self):
        """Signal without SL should still parse (SL = None)."""
        text = "Gold buy now 2140 - 2145\nTP: 2150\nTP: 2155"
        s = parse_signal(text)
        assert s is not None
        assert s.sl is None

    def test_without_now_keyword(self):
        text = "Gold sell 4978 - 4982\nSL: 4986\nTP: 4975\nTP: 4973"
        s = parse_signal(text)
        assert s is not None
        assert s.direction == Direction.SELL


# ═══════════════════════════════════════════════════════════════════════
# NEW TRADE SIGNALS — SINGLE PRICE
# ═══════════════════════════════════════════════════════════════════════


class TestOpenSignalsSingle:
    def test_single_price_buy(self):
        text = "Gold buy 2150\nSL: 2140\nTP: 2160\nTP: 2170"
        s = parse_signal(text)
        assert s is not None
        assert s.entry_zone == (2150.0, 2150.0)
        assert s.direction == Direction.BUY

    def test_single_price_with_at(self):
        text = "Gold buy @ 2150\nSL: 2140\nTP: 2160\nTP: 2170"
        s = parse_signal(text)
        assert s is not None
        assert s.entry_zone == (2150.0, 2150.0)


# ═══════════════════════════════════════════════════════════════════════
# VALIDATION — INVALID SIGNALS
# ═══════════════════════════════════════════════════════════════════════


class TestValidation:
    def test_buy_with_sl_above_entry_rejected(self):
        """BUY with SL above entry zone = invalid."""
        text = "Gold buy now 2140 - 2145\nSL: 2150\nTP: 2160\nTP: 2170"
        s = parse_signal(text)
        assert s is None

    def test_sell_with_sl_below_entry_rejected(self):
        """SELL with SL below entry zone = invalid."""
        text = "Gold sell now 4978 - 4982\nSL: 4970\nTP: 4960\nTP: 4950"
        s = parse_signal(text)
        assert s is None


# ═══════════════════════════════════════════════════════════════════════
# CLOSE SIGNALS
# ═══════════════════════════════════════════════════════════════════════


class TestCloseSignals:
    def test_close_gold(self):
        s = parse_signal("Close gold")
        assert s is not None
        assert s.type == SignalType.CLOSE
        assert s.symbol == "XAUUSD"

    def test_close_all(self):
        s = parse_signal("Close all")
        assert s is not None
        assert s.type == SignalType.CLOSE

    def test_exit_trade(self):
        s = parse_signal("Exit trade")
        assert s is not None
        assert s.type == SignalType.CLOSE

    def test_close_xauusd(self):
        s = parse_signal("Close XAUUSD")
        assert s is not None
        assert s.type == SignalType.CLOSE
        assert s.symbol == "XAUUSD"


# ═══════════════════════════════════════════════════════════════════════
# PARTIAL CLOSE SIGNALS
# ═══════════════════════════════════════════════════════════════════════


class TestPartialClose:
    def test_close_half(self):
        s = parse_signal("Close half")
        assert s is not None
        assert s.type == SignalType.CLOSE_PARTIAL
        assert s.close_percent == 50.0

    def test_close_50_percent(self):
        s = parse_signal("Close 50%")
        assert s is not None
        assert s.type == SignalType.CLOSE_PARTIAL
        assert s.close_percent == 50.0

    def test_close_30_percent(self):
        s = parse_signal("Close 30% gold")
        assert s is not None
        assert s.type == SignalType.CLOSE_PARTIAL
        assert s.close_percent == 30.0

    def test_tp1_hit_close_partial(self):
        s = parse_signal("TP1 hit - close partial")
        assert s is not None
        assert s.type == SignalType.CLOSE_PARTIAL

    def test_secure_profits(self):
        s = parse_signal("Secure profits")
        assert s is not None
        assert s.type == SignalType.CLOSE_PARTIAL
        assert s.close_percent == 50.0  # default


# ═══════════════════════════════════════════════════════════════════════
# SL MODIFICATION SIGNALS
# ═══════════════════════════════════════════════════════════════════════


class TestModifySL:
    def test_move_sl_to_breakeven(self):
        s = parse_signal("Move SL to breakeven")
        assert s is not None
        assert s.type == SignalType.MODIFY_SL
        assert s.new_sl == 0.0  # sentinel for breakeven

    def test_move_sl_to_be(self):
        s = parse_signal("Move SL to BE")
        assert s is not None
        assert s.type == SignalType.MODIFY_SL
        assert s.new_sl == 0.0

    def test_sl_to_entry(self):
        s = parse_signal("SL to entry")
        assert s is not None
        assert s.type == SignalType.MODIFY_SL

    def test_update_sl_with_price(self):
        s = parse_signal("Update SL: 4978")
        assert s is not None
        assert s.type == SignalType.MODIFY_SL
        assert s.new_sl == 4978.0

    def test_new_sl_with_price(self):
        s = parse_signal("New SL: 4980.50")
        assert s is not None
        assert s.type == SignalType.MODIFY_SL
        assert s.new_sl == 4980.50


# ═══════════════════════════════════════════════════════════════════════
# TP MODIFICATION SIGNALS
# ═══════════════════════════════════════════════════════════════════════


class TestModifyTP:
    def test_new_tp(self):
        s = parse_signal("New TP: 4965")
        assert s is not None
        assert s.type == SignalType.MODIFY_TP
        assert s.new_tp == 4965.0

    def test_update_tp(self):
        s = parse_signal("Update TP: 4960.50")
        assert s is not None
        assert s.type == SignalType.MODIFY_TP
        assert s.new_tp == 4960.50


# ═══════════════════════════════════════════════════════════════════════
# NON-SIGNAL MESSAGES (should return None)
# ═══════════════════════════════════════════════════════════════════════


class TestNonSignals:
    def test_empty_string(self):
        assert parse_signal("") is None

    def test_random_text(self):
        assert parse_signal("Hello everyone, good morning!") is None

    def test_market_commentary(self):
        assert parse_signal("Gold is looking bullish today, might push to 2200") is None

    def test_just_numbers(self):
        assert parse_signal("2150 2160 2170") is None

    def test_partial_signal_no_direction(self):
        assert parse_signal("Gold 2150\nSL: 2140") is None


# ═══════════════════════════════════════════════════════════════════════
# FORMAT PARSED SIGNAL
# ═══════════════════════════════════════════════════════════════════════


class TestFormatParsedSignal:
    def test_format_open_signal(self):
        text = "Gold sell now 4978 - 4982\nSL: 4986\nTP: 4975\nTP: 4973"
        s = parse_signal(text)
        formatted = format_parsed_signal(s)
        assert "SELL" in formatted
        assert "XAUUSD" in formatted
        assert "4978" in formatted
        assert "4982" in formatted
        assert "4986" in formatted

    def test_format_close_signal(self):
        s = parse_signal("Close gold")
        formatted = format_parsed_signal(s)
        assert "CLOSE" in formatted
        assert "XAUUSD" in formatted

    def test_format_partial_close(self):
        s = parse_signal("Close 50%")
        formatted = format_parsed_signal(s)
        assert "50%" in formatted

    def test_format_sl_breakeven(self):
        s = parse_signal("Move SL to breakeven")
        formatted = format_parsed_signal(s)
        assert "BREAKEVEN" in formatted

    def test_format_tp_update(self):
        s = parse_signal("New TP: 4965")
        formatted = format_parsed_signal(s)
        assert "4965" in formatted
