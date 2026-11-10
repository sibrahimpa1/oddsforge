from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from oddsforge.markets.derive import (
    asian_breakdown,
    effective_prob,
    ev_from_breakdown,
    fair_price_from_breakdown,
    market_ladder,
    total_breakdown,
)
from oddsforge.model.dixon_coles import fit_rho, lambdas_from_1x2, outcome_probs, score_matrix
from oddsforge.model.engine import EngineConfig, walk_forward
from oddsforge.model.ratings import RatingParams, fit_ratings


def test_score_matrix_is_a_distribution_and_rho_moves_draws():
    m0 = score_matrix(1.5, 1.1, 0.0)
    m1 = score_matrix(1.5, 1.1, -0.1)
    assert m0.sum() == pytest.approx(1.0)
    assert outcome_probs(m1)[1] > outcome_probs(m0)[1]  # negative rho adds 0-0 / 1-1 mass
    assert (m0 >= 0).all()


def test_markets_are_coherent_with_the_matrix():
    m = score_matrix(1.7, 0.9, -0.06)
    lad = market_ladder(m)
    x = lad["1x2"]
    assert x["home"] + x["draw"] + x["away"] == pytest.approx(1.0)
    # AH 0.0 home (draw no bet) and AH -0.5 home (= home win) must agree with 1X2
    dnb = asian_breakdown(m, 0.0, "home")
    assert dnb["void"] == pytest.approx(x["draw"])
    assert asian_breakdown(m, -0.5, "home")["won"] == pytest.approx(x["home"])
    assert effective_prob(dnb) == pytest.approx(x["home"] / (x["home"] + x["away"]))
    # over 2.5 + under 2.5 = 1, and fair prices give zero EV
    o, u = total_breakdown(m, 2.5, "over"), total_breakdown(m, 2.5, "under")
    assert o["won"] + u["won"] == pytest.approx(1.0)
    for b in (o, u, asian_breakdown(m, -0.75, "home"), asian_breakdown(m, 0.25, "away")):
        assert ev_from_breakdown(b, fair_price_from_breakdown(b)) == pytest.approx(0.0, abs=1e-9)
    assert lad["xg_home"] == pytest.approx(1.7, abs=0.02)


def test_market_lambda_inversion_round_trips():
    m = score_matrix(1.6, 1.0, -0.05)
    ph, _, pa = outcome_probs(m)
    lh, la = lambdas_from_1x2(ph, pa, -0.05)
    assert (lh, la) == pytest.approx((1.6, 1.0), abs=0.01)


def test_fit_rho_recovers_sign():
    rng = np.random.default_rng(1)
    n = 6000
    lh, la = np.full(n, 1.4), np.full(n, 1.1)
    m = score_matrix(1.4, 1.1, -0.12)
    flat = rng.choice(m.size, size=n, p=m.ravel())
    hg, ag = np.divmod(flat, m.shape[1])
    assert fit_rho(lh, la, hg, ag) == pytest.approx(-0.12, abs=0.05)


def _synthetic_league(seasons=3, seed=0):
    rng = np.random.default_rng(seed)
    teams = [f"t{i}" for i in range(10)]
    strength = {t: s for t, s in zip(teams, np.linspace(-0.4, 0.4, 10), strict=True)}
    rows, t0, gid = [], datetime(2020, 3, 1), 0
    for season in range(seasons):
        for rnd in range(18):
            day = t0 + timedelta(days=365 * season + 7 * rnd)
            order = rng.permutation(teams)
            for h, a in zip(order[::2], order[1::2], strict=True):
                lh = np.exp(0.2 + 0.25 + strength[h] - strength[a] * 0.5)
                la = np.exp(0.2 + strength[a] - strength[h] * 0.5)
                rows.append(
                    {
                        "id": gid,
                        "season": str(2020 + season),
                        "kickoff": day,
                        "home_id": h,
                        "away_id": a,
                        "hg": float(rng.poisson(lh)),
                        "ag": float(rng.poisson(la)),
                        "hxg": lh,
                        "axg": la,
                        "knockout": False,
                        "status": "final",
                    }
                )
                gid += 1
    df = pd.DataFrame(rows)
    df["kickoff"] = pd.to_datetime(df["kickoff"])
    return df, strength


def test_ratings_recover_strength_order():
    df, strength = _synthetic_league()
    arr = (
        df.kickoff.to_numpy("datetime64[s]"),
        df.home_id.to_numpy(),
        df.away_id.to_numpy(),
        df.hg.to_numpy(float),
        df.ag.to_numpy(float),
        df.hxg.to_numpy(float),
        df.axg.to_numpy(float),
    )
    r = fit_ratings(datetime(2023, 1, 1), *arr, RatingParams(xg_weight=1.0, ridge=1.0, half_life_days=2000))
    net = {t: r.attack[t] + r.defence[t] for t in strength}
    assert np.corrcoef([strength[t] for t in strength], [net[t] for t in strength])[0, 1] > 0.95
    assert r.home > 0.1


def test_future_results_cannot_change_a_past_rating():
    """The core leakage guarantee: a rating fitted as of T is identical whatever happens after T."""
    df, _ = _synthetic_league()
    as_of = datetime(2021, 6, 1)
    tampered = df.copy()
    tampered.loc[tampered.kickoff >= as_of, ["hg", "ag", "hxg", "axg"]] = [9.0, 0.0, 5.0, 0.1]

    def fit(frame):
        arr = (
            frame.kickoff.to_numpy("datetime64[s]"),
            frame.home_id.to_numpy(),
            frame.away_id.to_numpy(),
            frame.hg.to_numpy(float),
            frame.ag.to_numpy(float),
            frame.hxg.to_numpy(float),
            frame.axg.to_numpy(float),
        )
        return fit_ratings(as_of, *arr, RatingParams())

    a, b = fit(df), fit(tampered)
    assert a.attack == pytest.approx(b.attack) and a.defence == pytest.approx(b.defence)


def test_walk_forward_is_point_in_time():
    df, _ = _synthetic_league()
    wf = walk_forward(EngineConfig(league="SYN", use_context=False), datetime(2020, 6, 1), df=df)
    assert len(wf) > 100
    assert (pd.to_datetime(wf.as_of) <= pd.to_datetime(wf.kickoff)).all()
    assert np.allclose(wf[["p_home", "p_draw", "p_away"]].sum(axis=1), 1.0)
