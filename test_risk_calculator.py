"""Tests for risk_calculator.py — lot sizing and jitter."""

import pytest
from models import Direction
from risk_calculator import (
    calculate_lot_size,
    calculate_sl_distance,
    calculate_sl_with_jitter,
    calculate_tp_with_jitter,
)


class TestCalculateLotSize:
    def test_basic_calculation(self):
        """$10k account, 1% risk, $10 SL → should be ~0.10 lots."""
        lot = calculate_lot_size(
            account_balance=10000,
            risk_percent=1.0,
            sl_distance=10.0,  # $10 SL distance
            max_lot_size=5.0,
            jitter_percent=0.0,
        )
        # risk_amount = 100, sl_pips = 10/0.01 = 1000, lot = 100 / (1000 * 1) = 0.10
        assert lot == 0.10

    def test_6k_account(self):
        """$6k account, 1% risk, $8 SL."""
        lot = calculate_lot_size(
            account_balance=6000,
            risk_percent=1.0,
            sl_distance=8.0,
            max_lot_size=0.5,
            jitter_percent=0.0,
        )
        # risk = 60, sl_pips = 800, lot = 60 / 800 = 0.075 → rounds to 0.07 or 0.08
        assert lot in (0.07, 0.08)

    def test_25k_account(self):
        """$25k account, 0.5% risk, $6 SL."""
        lot = calculate_lot_size(
            account_balance=25000,
            risk_percent=0.5,
            sl_distance=6.0,
            max_lot_size=2.0,
            jitter_percent=0.0,
        )
        # risk = 125, sl_pips = 600, lot = 125 / 600 = 0.2083 → 0.21
        assert lot == 0.21

    def test_max_lot_cap(self):
        """Lot size should not exceed max_lot_size."""
        lot = calculate_lot_size(
            account_balance=100000,
            risk_percent=5.0,
            sl_distance=2.0,
            max_lot_size=1.0,
            jitter_percent=0.0,
        )
        assert lot == 1.0

    def test_minimum_lot(self):
        """Tiny account should still return minimum 0.01."""
        lot = calculate_lot_size(
            account_balance=100,
            risk_percent=0.1,
            sl_distance=50.0,
            max_lot_size=5.0,
            jitter_percent=0.0,
        )
        assert lot == 0.01

    def test_zero_balance(self):
        lot = calculate_lot_size(0, 1.0, 10.0, 1.0)
        assert lot == 0.0

    def test_zero_sl(self):
        lot = calculate_lot_size(10000, 1.0, 0, 1.0)
        assert lot == 0.0

    def test_jitter_varies_output(self):
        """With jitter, repeated calculations should produce different results."""
        results = set()
        for _ in range(50):
            lot = calculate_lot_size(
                account_balance=50000,
                risk_percent=2.0,
                sl_distance=5.0,
                max_lot_size=10.0,
                jitter_percent=5.0,
            )
            results.add(lot)
        # Larger lot size makes jitter visible after rounding
        assert len(results) > 1

    def test_jitter_stays_within_range(self):
        """Jittered lot should be within ±jitter% of base."""
        base = 0.10  # expected base for 10k, 1%, $10 SL
        for _ in range(100):
            lot = calculate_lot_size(
                account_balance=10000,
                risk_percent=1.0,
                sl_distance=10.0,
                max_lot_size=5.0,
                jitter_percent=5.0,
            )
            assert 0.09 <= lot <= 0.11  # within ~10% of 0.10


class TestSLDistance:
    def test_buy_sl_below(self):
        assert calculate_sl_distance(2150, 2140) == 10.0

    def test_sell_sl_above(self):
        assert calculate_sl_distance(4980, 4986) == 6.0


class TestSLJitter:
    def test_jitter_varies(self):
        results = set()
        for _ in range(20):
            sl = calculate_sl_with_jitter(4986.0, 0.8, Direction.SELL)
            results.add(sl)
        assert len(results) > 1

    def test_no_jitter(self):
        sl = calculate_sl_with_jitter(4986.0, 0.0, Direction.SELL)
        assert sl == 4986.0


class TestTPJitter:
    def test_jitter_varies(self):
        results = set()
        for _ in range(20):
            tp = calculate_tp_with_jitter(4973.0, 0.8, Direction.SELL)
            results.add(tp)
        assert len(results) > 1
