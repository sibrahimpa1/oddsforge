"""Read every market off a single score matrix (rows = home goals, cols = away goals)."""

from __future__ import annotations

import numpy as np

from .settlement import settle_asian, settle_total

QUARTER_AH_LINES = [x / 4 for x in range(-10, 11)]  # -2.5 .. +2.5
TOTAL_LINES = [1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5, 4.5]


def one_x_two(m: np.ndarray) -> dict[str, float]:
    return {
        "home": float(np.tril(m, -1).sum()),
        "draw": float(np.trace(m)),
        "away": float(np.triu(m, 1).sum()),
    }


def btts(m: np.ndarray) -> dict[str, float]:
    yes = float(m[1:, 1:].sum())
    return {"yes": yes, "no": 1 - yes}


def _goal_grid(m: np.ndarray):
    n = m.shape[0]
    h, a = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    return h, a


def asian_breakdown(m: np.ndarray, home_line: float, side: str) -> dict[str, float]:
    """Probabilities of each settlement result for one side of an Asian handicap."""
    h, a = _goal_grid(m)
    out = {"won": 0.0, "half_won": 0.0, "void": 0.0, "half_lost": 0.0, "lost": 0.0}
    # settlement depends only on goal difference: aggregate the matrix by diff first
    diffs = (h - a).ravel()
    probs = m.ravel()
    for d in np.unique(diffs):
        p = float(probs[diffs == d].sum())
        hg, ag = (int(d), 0) if d >= 0 else (0, int(-d))
        out[settle_asian(hg, ag, side, home_line, 2.0).result] += p
    return out


def total_breakdown(m: np.ndarray, line: float, side: str) -> dict[str, float]:
    h, a = _goal_grid(m)
    tot = (h + a).ravel()
    probs = m.ravel()
    out = {"won": 0.0, "half_won": 0.0, "void": 0.0, "half_lost": 0.0, "lost": 0.0}
    for t in np.unique(tot):
        p = float(probs[tot == t].sum())
        out[settle_total(int(t), 0, side, line, 2.0).result] += p
    return out


def ev_from_breakdown(b: dict[str, float], price: float) -> float:
    """Expected return per unit stake, correctly handling pushes and half results."""
    ret = b["won"] * price + b["half_won"] * (price + 1) / 2 + b["void"] * 1.0 + b["half_lost"] * 0.5
    return ret - 1.0


def fair_price_from_breakdown(b: dict[str, float]) -> float:
    """Price at which EV = 0. Return is linear in price: A*price + B = 1."""
    a = b["won"] + b["half_won"] / 2
    c = b["half_won"] / 2 + b["void"] + b["half_lost"] * 0.5
    return float("inf") if a <= 0 else (1 - c) / a


def effective_prob(b: dict[str, float]) -> float:
    """Win probability of the equivalent no-push bet (1 / fair price)."""
    fp = fair_price_from_breakdown(b)
    return 0.0 if fp == float("inf") else 1 / fp


def market_ladder(m: np.ndarray) -> dict:
    """Full set of model prices shown on the match page."""
    h, a = _goal_grid(m)
    lam_h = float((h * m).sum())
    lam_a = float((a * m).sum())
    ah = []
    for line in QUARTER_AH_LINES:
        bh, ba = asian_breakdown(m, line, "home"), asian_breakdown(m, line, "away")
        ah.append(
            {
                "line": line,
                "home_fair": fair_price_from_breakdown(bh),
                "away_fair": fair_price_from_breakdown(ba),
                "home_prob": effective_prob(bh),
                "away_prob": effective_prob(ba),
            }
        )
    totals = []
    for line in TOTAL_LINES:
        bo, bu = total_breakdown(m, line, "over"), total_breakdown(m, line, "under")
        totals.append(
            {
                "line": line,
                "over_fair": fair_price_from_breakdown(bo),
                "under_fair": fair_price_from_breakdown(bu),
                "over_prob": effective_prob(bo),
                "under_prob": effective_prob(bu),
            }
        )
    flat = [(float(m[i, j]), i, j) for i in range(min(6, m.shape[0])) for j in range(min(6, m.shape[1]))]
    flat.sort(reverse=True)
    x = one_x_two(m)
    return {
        "xg_home": lam_h,
        "xg_away": lam_a,
        "xg_total": lam_h + lam_a,
        "xg_diff": lam_h - lam_a,
        "1x2": x,
        "double_chance": {
            "1X": x["home"] + x["draw"],
            "12": x["home"] + x["away"],
            "X2": x["draw"] + x["away"],
        },
        "dnb": {"home": x["home"] / (x["home"] + x["away"]), "away": x["away"] / (x["home"] + x["away"])},
        "btts": btts(m),
        "team_totals": {
            "home_over_0_5": float(m[1:, :].sum()),
            "home_over_1_5": float(m[2:, :].sum()),
            "away_over_0_5": float(m[:, 1:].sum()),
            "away_over_1_5": float(m[:, 2:].sum()),
        },
        "asian_handicap": ah,
        "totals": totals,
        "top_scores": [{"score": f"{i}-{j}", "prob": p} for p, i, j in flat[:8]],
        "matrix": [[round(float(m[i, j]), 5) for j in range(7)] for i in range(7)],
    }
