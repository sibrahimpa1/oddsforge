"""Team strength: a time-decayed, opponent-adjusted Poisson model of expected goals.

log E[goals for team i vs j at venue v] = mu + home*[v == i] + attack_i - defence_j

Choices, and why:
- Target is a blend of xG and goals (`xg_weight`). Goals are what settle bets, but they carry a
  lot of finishing and goalkeeping noise; xG is the more stable estimate of chance quality.
  A pure-goals fit chases finishing streaks; a pure-xG fit ignores real finishing skill and
  penalties. The weight is tuned on early seasons only, then frozen.
- Exponential time decay (`half_life_days`) instead of a hard window: last month counts most,
  but one bad week cannot overturn a season.
- L2 shrinkage towards league average (`ridge`) is a Bayesian prior in disguise. It is what
  stops a 4-game sample from producing an extreme rating, and it gives expansion teams a
  sensible starting point (slightly below average, see `NEW_TEAM_PRIOR`).
- Ratings are opponent-adjusted by construction: beating weak teams earns less.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from scipy.optimize import minimize

NEW_TEAM_PRIOR = (-0.08, -0.08)  # (attack, defence) for clubs with almost no history


@dataclass
class RatingParams:
    half_life_days: float = 240.0
    xg_weight: float = 0.6
    ridge: float = 4.0
    window_days: int = 3 * 365


@dataclass
class Ratings:
    as_of: datetime
    mu: float
    home: float
    attack: dict[str, float]
    defence: dict[str, float]
    n_obs: dict[str, float] = field(default_factory=dict)

    def lambdas(self, home_id: str, away_id: str, neutral: bool = False) -> tuple[float, float]:
        ah, dh = self.attack.get(home_id, NEW_TEAM_PRIOR[0]), self.defence.get(home_id, NEW_TEAM_PRIOR[1])
        aa, da = self.attack.get(away_id, NEW_TEAM_PRIOR[0]), self.defence.get(away_id, NEW_TEAM_PRIOR[1])
        hadv = 0.0 if neutral else self.home
        return float(np.exp(self.mu + hadv + ah - da)), float(np.exp(self.mu + aa - dh))

    def table(self) -> list[dict]:
        rows = []
        for t in self.attack:
            rows.append(
                {
                    "team": t,
                    "attack": self.attack[t],
                    "defence": self.defence[t],
                    "net": self.attack[t] + self.defence[t],
                    "weight": self.n_obs.get(t, 0.0),
                }
            )
        return sorted(rows, key=lambda r: -r["net"])


def fit_ratings(
    as_of: datetime,
    kickoff: np.ndarray,  # datetime64[s]
    home: np.ndarray,
    away: np.ndarray,
    hg: np.ndarray,
    ag: np.ndarray,
    hxg: np.ndarray,  # NaN where xG is missing
    axg: np.ndarray,
    params: RatingParams,
    prev: Ratings | None = None,
) -> Ratings:
    """Fit on matches strictly before `as_of`. The caller cannot leak future games in."""
    t0 = np.datetime64(as_of, "s")
    age = (t0 - kickoff).astype("timedelta64[s]").astype(float) / 86400.0
    sel = (age > 0) & (age <= params.window_days)
    if sel.sum() < 30:
        raise ValueError("not enough history to fit ratings")
    home, away, age = home[sel], away[sel], age[sel]
    w = 0.5 ** (age / params.half_life_days)

    def blend(goals, xg):
        g = goals[sel].astype(float)
        x = xg[sel]
        return np.where(np.isnan(x), g, params.xg_weight * x + (1 - params.xg_weight) * g)

    yh, ya = blend(hg, hxg), blend(ag, axg)
    teams = sorted(set(home) | set(away))
    ix = {t: i for i, t in enumerate(teams)}
    hi = np.array([ix[t] for t in home])
    ai = np.array([ix[t] for t in away])
    n = len(teams)
    nobs = np.bincount(hi, w, n) + np.bincount(ai, w, n)
    prior = np.where(nobs < 3.0, NEW_TEAM_PRIOR[0], 0.0)

    # parameter vector: [mu, home, att(n), def(n)]
    x0 = np.zeros(2 + 2 * n)
    x0[0] = np.log(max(np.average(np.r_[yh, ya], weights=np.r_[w, w]), 0.3))
    x0[1] = 0.25
    if prev is not None:  # warm start: much faster convergence week to week
        x0[0], x0[1] = prev.mu, prev.home
        for t, i in ix.items():
            x0[2 + i] = prev.attack.get(t, 0.0)
            x0[2 + n + i] = prev.defence.get(t, 0.0)

    lam_r = params.ridge

    def f(x):
        mu, hadv = x[0], x[1]
        att, dfn = x[2 : 2 + n], x[2 + n :]
        eh = mu + hadv + att[hi] - dfn[ai]
        ea = mu + att[ai] - dfn[hi]
        lh, la = np.exp(eh), np.exp(ea)
        nll = (w * (lh - yh * eh)).sum() + (w * (la - ya * ea)).sum()
        pen = lam_r * (((att - prior) ** 2).sum() + ((dfn - prior) ** 2).sum())
        rh, ra = w * (lh - yh), w * (la - ya)
        g = np.zeros_like(x)
        g[0] = rh.sum() + ra.sum()
        g[1] = rh.sum()
        g[2 : 2 + n] = np.bincount(hi, rh, n) + np.bincount(ai, ra, n) + 2 * lam_r * (att - prior)
        g[2 + n :] = -np.bincount(ai, rh, n) - np.bincount(hi, ra, n) + 2 * lam_r * (dfn - prior)
        return nll + pen, g

    res = minimize(f, x0, jac=True, method="L-BFGS-B", options={"maxiter": 500})
    x = res.x
    return Ratings(
        as_of=as_of,
        mu=float(x[0]),
        home=float(x[1]),
        attack={t: float(x[2 + i]) for t, i in ix.items()},
        defence={t: float(x[2 + n + i]) for t, i in ix.items()},
        n_obs={t: float(nobs[i]) for t, i in ix.items()},
    )
