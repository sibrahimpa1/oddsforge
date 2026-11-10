"""Score distribution: independent Poisson goals with the Dixon-Coles low-score correction.

Every market probability in the app (1X2, Asian handicap, totals, BTTS) is read from ONE score
matrix, so the markets are coherent by construction: the draw probability is exactly the sum of
the diagonal, and P(home -0.5) equals P(home win). A separate 1X2 classifier would not give
that guarantee.

Dixon-Coles adds one parameter, rho, that moves probability between 0-0/1-1 and 1-0/0-1.
Independent Poisson under-predicts low-scoring draws in soccer; rho < 0 fixes most of it.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import poisson

MAX_GOALS = 10


def tau_matrix(lh: float, la: float, rho: float) -> np.ndarray:
    t = np.ones((2, 2))
    t[0, 0] = 1 - lh * la * rho
    t[0, 1] = 1 + lh * rho
    t[1, 0] = 1 + la * rho
    t[1, 1] = 1 - rho
    return t


def score_matrix(lh: float, la: float, rho: float = 0.0, max_goals: int = MAX_GOALS) -> np.ndarray:
    """P(home = i, away = j) for i, j in 0..max_goals (tail mass folded into the last row/col)."""
    g = np.arange(max_goals + 1)
    ph = poisson.pmf(g, lh)
    pa = poisson.pmf(g, la)
    ph[-1] += 1 - ph.sum()
    pa[-1] += 1 - pa.sum()
    m = np.outer(ph, pa)
    m[:2, :2] *= tau_matrix(lh, la, rho)
    m = np.clip(m, 0, None)
    return m / m.sum()


def outcome_probs(m: np.ndarray) -> tuple[float, float, float]:
    return float(np.tril(m, -1).sum()), float(np.trace(m)), float(np.triu(m, 1).sum())


def _dc_loglik(
    rho: float, lh: np.ndarray, la: np.ndarray, hg: np.ndarray, ag: np.ndarray, w: np.ndarray
) -> float:
    ll = poisson.logpmf(hg, lh) + poisson.logpmf(ag, la)
    t = np.ones_like(lh)
    m00 = (hg == 0) & (ag == 0)
    m01 = (hg == 0) & (ag == 1)
    m10 = (hg == 1) & (ag == 0)
    m11 = (hg == 1) & (ag == 1)
    t[m00] = 1 - lh[m00] * la[m00] * rho
    t[m01] = 1 + lh[m01] * rho
    t[m10] = 1 + la[m10] * rho
    t[m11] = 1 - rho
    return float(-(w * (ll + np.log(np.clip(t, 1e-9, None)))).sum())


def fit_rho(lh, la, hg, ag, weights=None) -> float:
    """Maximum-likelihood rho given point-in-time expected goals and observed scores."""
    lh, la = np.asarray(lh, float), np.asarray(la, float)
    hg, ag = np.asarray(hg, int), np.asarray(ag, int)
    w = np.ones_like(lh) if weights is None else np.asarray(weights, float)
    res = minimize_scalar(_dc_loglik, bounds=(-0.3, 0.15), args=(lh, la, hg, ag, w), method="bounded")
    return float(res.x)


def lambdas_from_1x2(
    p_home: float, p_away: float, rho: float = -0.05, total_hint: float = 2.8
) -> tuple[float, float]:
    """Invert the score model: expected goals implied by a (no-vig) 1X2 market.
    Two equations (home and away probability), two unknowns. Used to read the market's view of
    the game in goals, so model and market can be compared on the same scale."""

    def loss(x):
        lh, la = np.exp(x)
        ph, _, pa = outcome_probs(score_matrix(lh, la, rho))
        return (ph - p_home) ** 2 + (pa - p_away) ** 2

    x0 = np.log([total_hint * 0.55, total_hint * 0.45])
    res = minimize(loss, x0, method="Nelder-Mead", options={"xatol": 1e-6, "fatol": 1e-12, "maxiter": 400})
    lh, la = np.exp(res.x)
    return float(lh), float(la)
