import pytest

from oddsforge.markets.settlement import settle_asian, settle_leg, settle_total

P = 1.90


@pytest.mark.parametrize(
    "hg,ag,line,side,result,factor",
    [
        (1, 0, -0.5, "home", "won", P),
        (1, 1, -0.5, "home", "lost", 0.0),
        (1, 1, 0.0, "home", "void", 1.0),
        (2, 1, -1.0, "home", "void", 1.0),
        (3, 1, -1.0, "home", "won", P),
        # quarter lines: -0.75 = half on -0.5, half on -1.0
        (2, 1, -0.75, "home", "half_won", (P + 1) / 2),
        (3, 1, -0.75, "home", "won", P),
        (1, 1, -0.75, "home", "lost", 0.0),
        # -0.25 = half on 0, half on -0.5
        (1, 1, -0.25, "home", "half_lost", 0.5),
        (1, 1, -0.25, "away", "half_won", (P + 1) / 2),
        (0, 1, 0.25, "home", "lost", 0.0),
        (1, 1, 0.25, "home", "half_won", (P + 1) / 2),
        # away side is the mirror of the home line
        (0, 0, -1.5, "away", "won", P),
        (2, 0, -1.5, "away", "lost", 0.0),
    ],
)
def test_asian_handicap(hg, ag, line, side, result, factor):
    out = settle_asian(hg, ag, side, line, P)
    assert out.result == result
    assert out.factor == pytest.approx(factor)


@pytest.mark.parametrize(
    "total,line,side,result",
    [
        (3, 2.5, "over", "won"),
        (2, 2.5, "over", "lost"),
        (2, 2.0, "over", "void"),
        (3, 2.25, "over", "won"),
        (2, 2.25, "over", "half_lost"),
        (2, 2.25, "under", "half_won"),
        (3, 2.75, "over", "half_won"),
        (2, 2.75, "under", "won"),
    ],
)
def test_totals(total, line, side, result):
    assert settle_total(total, 0, side, line, P).result == result


def test_home_and_away_ah_are_complementary_payouts():
    # For any score and line, the bookmaker's settlement must be zero-sum at even money.
    for hg in range(5):
        for ag in range(5):
            for q in range(-10, 11):
                line = q / 4
                h = settle_asian(hg, ag, "home", line, 2.0).factor
                a = settle_asian(hg, ag, "away", line, 2.0).factor
                assert h + a == pytest.approx(2.0)


def test_1x2_and_btts():
    assert settle_leg("1x2", "draw", None, 3.3, 1, 1).factor == 3.3
    assert settle_leg("1x2", "home", None, 2.0, 0, 1).result == "lost"
    assert settle_leg("btts", "yes", None, 1.8, 1, 2).result == "won"
    assert settle_leg("btts", "no", None, 2.0, 0, 2).result == "won"
