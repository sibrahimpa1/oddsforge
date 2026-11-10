"""Odds maths: implied probability, overround, vig removal, expected value and Kelly staking.

Vig removal matters more than it looks. Bookmakers do not spread their margin evenly: longshots
carry more of it (favourite-longshot bias). Simple normalisation ("multiplicative") therefore
overstates longshot probabilities, and a model compared against it will "find" fake value on
outsiders. The power and Shin methods correct for this; power is the default here.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from scipy.optimize import brentq


def implied(prices: Sequence[float]) -> list[float]:
    if any(p <= 1.0 for p in prices):
        raise ValueError(f"decimal odds must be > 1.0, got {prices}")
    return [1.0 / p for p in prices]


def overround(prices: Sequence[float]) -> float:
    """Booksum minus one (0.05 = 5% margin)."""
    return sum(implied(prices)) - 1.0


def devig_multiplicative(prices: Sequence[float]) -> list[float]:
    q = implied(prices)
    s = sum(q)
    return [x / s for x in q]


def devig_additive(prices: Sequence[float]) -> list[float]:
    q = implied(prices)
    excess = (sum(q) - 1.0) / len(q)
    p = [max(x - excess, 1e-9) for x in q]
    s = sum(p)
    return [x / s for x in p]


def devig_power(prices: Sequence[float]) -> list[float]:
    """Find k so that sum(q_i ** k) == 1. k > 1 shrinks longshots more than favourites."""
    q = implied(prices)
    if abs(sum(q) - 1.0) < 1e-12:
        return q
    k = brentq(lambda k: sum(x**k for x in q) - 1.0, 0.2, 5.0)
    return [x**k for x in q]


def devig_shin(prices: Sequence[float]) -> list[float]:
    """Shin (1993): margin as protection against a share z of insider money."""
    q = implied(prices)
    b = sum(q)
    if abs(b - 1.0) < 1e-12:
        return q

    def probs(z: float) -> list[float]:
        return [(math.sqrt(z * z + 4 * (1 - z) * x * x / b) - z) / (2 * (1 - z)) for x in q]

    z = brentq(lambda z: sum(probs(z)) - 1.0, 0.0, 0.4)
    return probs(z)


DEVIG = {
    "multiplicative": devig_multiplicative,
    "additive": devig_additive,
    "power": devig_power,
    "shin": devig_shin,
}


def devig(prices: Sequence[float], method: str = "power") -> list[float]:
    return DEVIG[method](prices)


def expected_value(prob: float, price: float) -> float:
    """EV per unit staked for a bet that either wins (pays price) or loses."""
    return prob * price - 1.0


def kelly_fraction(prob: float, price: float, fraction: float = 0.25, cap: float = 0.05) -> float:
    """Fractional Kelly, capped. Full Kelly assumes the probability is exact; ours is not."""
    b = price - 1.0
    if b <= 0:
        return 0.0
    f = (b * prob - (1.0 - prob)) / b
    return max(0.0, min(cap, f * fraction))


def fair_price(prob: float) -> float:
    return math.inf if prob <= 0 else 1.0 / prob


def clv(bet_price: float, closing_fair_prob: float) -> float:
    """Closing-line value: expected return of the taken price under the no-vig closing probability.
    Positive CLV means the market later moved towards our side; it is the best available
    short-sample signal that a bettor has an edge, because results are far noisier."""
    return bet_price * closing_fair_prob - 1.0
