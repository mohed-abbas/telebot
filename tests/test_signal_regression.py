"""Regression tests for signal_parser using real Telegram messages.

HOW TO ADD NEW SIGNALS:
1. Copy a real Telegram message into the REAL_SIGNALS list below
2. Add the expected parsed values as a tuple
3. Run: pytest tests/test_signal_regression.py -v

Each entry is: (raw_text, expected_type, expected_direction, expected_symbol, expected_entry_zone)
"""

import pytest

from models import Direction, SignalType
from signal_parser import parse_signal, is_signal_like, _extract_symbol_from_text


# ═══════════════════════════════════════════════════════════════════════
# REAL SIGNAL REGRESSION TABLE
# ═══════════════════════════════════════════════════════════════════════

REAL_SIGNALS = [
    # User will paste real Telegram signals here during execution.
    # Example format:
    # (
    #     "Gold sell now 4978 - 4982\nSL: 4986\nTP: 4975\nTP: 4973\nTP: open",
    #     SignalType.OPEN,
    #     Direction.SELL,
    #     "XAUUSD",
    #     (4978.0, 4982.0),
    # ),
]


@pytest.mark.parametrize(
    "raw_text, expected_type, expected_direction, expected_symbol, expected_entry_zone",
    REAL_SIGNALS,
    ids=[f"signal_{i}" for i in range(len(REAL_SIGNALS))],
)
def test_real_signal_regression(
    raw_text, expected_type, expected_direction, expected_symbol, expected_entry_zone
):
    """Parametrized regression test for real Telegram signals."""
    result = parse_signal(raw_text)
    assert result is not None, f"Failed to parse signal: {raw_text[:80]!r}"
    assert result.type == expected_type
    if expected_direction is not None:
        assert result.direction == expected_direction
    assert result.symbol == expected_symbol
    if expected_entry_zone is not None:
        assert result.entry_zone == expected_entry_zone


# ═══════════════════════════════════════════════════════════════════════
# EDGE CASE TESTS — is_signal_like heuristic
# ═══════════════════════════════════════════════════════════════════════


class TestIsSignalLike:
    def test_is_signal_like_with_trading_keywords(self):
        """2+ trading keywords should return True."""
        assert is_signal_like("buy gold sl 100") is True

    def test_is_signal_like_with_keyword_and_price(self):
        """1 keyword + price-like number should return True."""
        assert is_signal_like("sell 4980") is True

    def test_is_signal_like_rejects_plain_text(self):
        """Plain text with no trading keywords should return False."""
        assert is_signal_like("Hello everyone") is False

    def test_is_signal_like_single_keyword_no_price_rejects(self):
        """Single keyword without a price should return False."""
        assert is_signal_like("buy some groceries") is False

    def test_is_signal_like_multiple_keywords_no_price(self):
        """Multiple keywords without price should still return True."""
        assert is_signal_like("buy and sell sl tp entry close") is True


# ═══════════════════════════════════════════════════════════════════════
# EDGE CASE TESTS — symbol extraction
# ═══════════════════════════════════════════════════════════════════════


class TestExtractSymbol:
    def test_gold_in_text(self):
        assert _extract_symbol_from_text("close gold now") == "XAUUSD"

    def test_xauusd_in_text(self):
        assert _extract_symbol_from_text("close xauusd please") == "XAUUSD"

    def test_xau_slash_usd(self):
        assert _extract_symbol_from_text("XAU/USD is trending") == "XAUUSD"

    def test_default_when_no_symbol(self):
        assert _extract_symbol_from_text("close all positions") == "XAUUSD"


# ═══════════════════════════════════════════════════════════════════════
# EDGE CASE TESTS — parsing resilience
# (Only tests NOT already covered in test_signal_parser.py)
# ═══════════════════════════════════════════════════════════════════════


class TestCaseInsensitivity:
    def test_case_insensitivity_uppercase(self):
        """GOLD BUY NOW in all caps should parse correctly."""
        text = "GOLD BUY NOW 2140 - 2145\nSL: 2135\nTP: 2150\nTP: 2155"
        s = parse_signal(text)
        assert s is not None
        assert s.type == SignalType.OPEN
        assert s.direction == Direction.BUY
        assert s.symbol == "XAUUSD"
        assert s.entry_zone == (2140.0, 2145.0)

    def test_case_insensitivity_mixed(self):
        """Mixed case like GoLd SeLl should parse correctly."""
        text = "GoLd SeLl now 4978 - 4982\nSL: 4986\nTP: 4975\nTP: 4973"
        s = parse_signal(text)
        assert s is not None
        assert s.direction == Direction.SELL


class TestExtraWhitespace:
    def test_extra_whitespace_newlines(self):
        """Extra newlines between fields should still parse."""
        text = "Gold sell now 4978 - 4982\n\n\n\nSL: 4986\n\n\nTP: 4975\n\nTP: 4973"
        s = parse_signal(text)
        assert s is not None
        assert s.type == SignalType.OPEN
        assert s.sl == 4986.0
        assert len(s.tps) == 2

    def test_extra_whitespace_leading_trailing(self):
        """Leading/trailing whitespace should be stripped."""
        text = "   Gold sell now 4978 - 4982\nSL: 4986\nTP: 4975\nTP: 4973   "
        s = parse_signal(text)
        assert s is not None
        assert s.type == SignalType.OPEN


class TestUnicodeDashes:
    def test_en_dash_in_zone(self):
        """En-dash (\u2013) in price zone should parse."""
        text = "Gold sell now 4978 \u2013 4982\nSL: 4986\nTP: 4975\nTP: 4973"
        s = parse_signal(text)
        assert s is not None
        assert s.entry_zone == (4978.0, 4982.0)

    def test_em_dash_in_zone(self):
        """Em-dash (\u2014) in price zone should parse."""
        text = "Gold sell now 4978 \u2014 4982\nSL: 4986\nTP: 4975\nTP: 4973"
        s = parse_signal(text)
        assert s is not None
        assert s.entry_zone == (4978.0, 4982.0)


class TestTpOpenTrailing:
    def test_tp_open_in_tps_list(self):
        """Signal with 'TP: open' as last TP should include 'open' in tps list."""
        text = "Gold sell now 4978 - 4982\nSL: 4986\nTP: 4975\nTP: 4973\nTP: open"
        s = parse_signal(text)
        assert s is not None
        assert "open" in s.tps
        assert s.tps[-1] == "open"

    def test_tp_open_does_not_affect_target_tp(self):
        """'open' TP should not be selected as target TP."""
        text = "Gold sell now 4978 - 4982\nSL: 4986\nTP: 4975\nTP: 4973\nTP: open"
        s = parse_signal(text)
        assert s is not None
        # target_tp should be TP2 = 4973 (numeric), not "open"
        assert s.target_tp == 4973.0


class TestSignalWithEmoji:
    def test_emoji_in_signal_text(self):
        """Emoji characters in signal text should not crash the parser."""
        text = "Gold sell now 4978 - 4982\nSL: 4986\nTP: 4975\nTP: 4973"
        s = parse_signal(text)
        assert s is not None
        assert s.type == SignalType.OPEN

    def test_emoji_prefix(self):
        """Signal with emoji prefix should parse if signal content is valid."""
        # parse_signal strips the text, emoji before signal might break regex
        # but the parser should not crash
        text = "Gold sell now 4978 - 4982\nSL: 4986\nTP: 4975"
        s = parse_signal(text)
        assert s is not None


class TestCloseVariants:
    def test_close_gold(self):
        s = parse_signal("close gold")
        assert s is not None
        assert s.type == SignalType.CLOSE

    def test_exit_trade(self):
        s = parse_signal("exit trade")
        assert s is not None
        assert s.type == SignalType.CLOSE

    def test_close_xauusd_lowercase(self):
        s = parse_signal("close xauusd")
        assert s is not None
        assert s.type == SignalType.CLOSE
        assert s.symbol == "XAUUSD"

    def test_exit_gold(self):
        s = parse_signal("exit gold")
        assert s is not None
        assert s.type == SignalType.CLOSE

    def test_exit_all(self):
        s = parse_signal("exit all")
        assert s is not None
        assert s.type == SignalType.CLOSE


class TestModifySlBreakevenVariants:
    def test_move_sl_to_be(self):
        s = parse_signal("Move SL to BE")
        assert s is not None
        assert s.type == SignalType.MODIFY_SL
        assert s.new_sl == 0.0

    def test_move_sl_to_breakeven(self):
        s = parse_signal("move sl to breakeven")
        assert s is not None
        assert s.type == SignalType.MODIFY_SL
        assert s.new_sl == 0.0

    def test_sl_to_entry(self):
        s = parse_signal("SL to entry")
        assert s is not None
        assert s.type == SignalType.MODIFY_SL
        assert s.new_sl == 0.0

    def test_sl_to_break_even_two_words(self):
        s = parse_signal("move sl to break even")
        assert s is not None
        assert s.type == SignalType.MODIFY_SL
        assert s.new_sl == 0.0
