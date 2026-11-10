import math

import pytest

from oddsforge.markets.odds import clv, devig, expected_value, fair_price, kelly_fraction, overround


def test_overround_and_implied():
    assert overround([2.0, 2.0]) == pytest.approx(0.0)
    assert overround([1.9, 1.9]) == pytest.approx(2 / 1.9 - 1)
    with pytest.raises(ValueError):
        overround([1.0, 3.0])


@pytest.mark.parametrize("method", ["multiplicative", "additive", "power", "shin"])
def test_devig_sums_to_one_and_keeps_order(method):
    prices = [1.55, 4.20, 6.00]
    p = devig(prices, method)
    assert sum(p) == pytest.approx(1.0, abs=1e-9)
    assert p[0] > p[1] > p[2]
    assert all(pi < 1 / pr for pi, pr in zip(p, prices, strict=True))  # every side loses some vig


def test_devig_fair_book_is_untouched():
    for method in ("multiplicative", "power", "shin"):
        assert devig([2.0, 4.0, 4.0], method) == pytest.approx([0.5, 0.25, 0.25])


def test_power_and_shin_take_more_margin_from_longshots():
    prices = [1.30, 5.50, 11.0]
    mult, power, shin = devig(prices, "multiplicative"), devig(prices, "power"), devig(prices, "shin")
    assert power[2] < mult[2] and shin[2] < mult[2]
    assert power[0] > mult[0] and shin[0] > mult[0]


def test_ev_kelly_clv():
    assert expected_value(0.5, 2.1) == pytest.approx(0.05)
    assert kelly_fraction(0.5, 2.0) == 0.0
    full = (1.1 * 0.55 - 0.45) / 1.1
    assert kelly_fraction(0.55, 2.1, fraction=1.0, cap=1.0) == pytest.approx(full)
    assert kelly_fraction(0.9, 3.0, fraction=1.0, cap=0.05) == 0.05
    assert clv(2.2, 0.5) == pytest.approx(0.1)
    assert math.isinf(fair_price(0.0))
