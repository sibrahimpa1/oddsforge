"""End-to-end research run: tune on early seasons, freeze, walk forward on later seasons,
evaluate probabilities and betting, audit for leakage, write data/reports/backtest.json and
store every point-in-time prediction (used by Replay mode in the app).

Protocol
- MLS: tune 2014-2018 (log-loss only, no betting results look at), report 2019-2026.
  Only closing odds exist for MLS in the free data, so MLS betting results are "model vs the
  close", the hardest benchmark. No CLV is possible there and none is claimed.
- EPL: tune 2016/17-2018/19, report 2019/20-2025/26. Opening AND closing prices exist, so bets
  are placed at the opening price and CLV is measured against Pinnacle's close.
"""

from __future__ import annotations

import itertools
import json
import logging
from datetime import UTC, datetime

import numpy as np
import pandas as pd
from sqlalchemy import delete, func, select

from ..config import settings
from ..db import KV, Match, OddsQuote, Prediction, session
from ..markets.odds import devig
from ..model.dixon_coles import fit_rho, lambdas_from_1x2, outcome_probs, score_matrix
from ..model.engine import EngineConfig, build_live_model, load_frame, walk_forward
from ..model.ratings import RatingParams, fit_ratings
from . import metrics as M
from .betting import Strategy, by_bucket, candidate_bets, quotes_frame, simulate

log = logging.getLogger(__name__)

MLS_TUNE = ("2015", "2018")
MLS_TEST_FROM = "2019"
EPL_TUNE = ("2016-17", "2018-19")
EPL_TEST_FROM = "2019-20"


def _quotes(league: str) -> pd.DataFrame:
    with session() as s:
        rows = s.execute(
            select(
                OddsQuote.match_id,
                OddsQuote.market,
                OddsQuote.line,
                OddsQuote.book,
                OddsQuote.timing,
                OddsQuote.price_a,
                OddsQuote.price_b,
                OddsQuote.price_c,
            )
            .join(Match, Match.id == OddsQuote.match_id)
            .where(Match.league == league)
        ).all()
    return quotes_frame(rows)


def _market_probs(q: pd.DataFrame, book: str, timing: str) -> dict[int, list[float]]:
    sub = q[(q.market == "1x2") & (q.book == book) & (q.timing == timing)]
    return {int(r.match_id): devig([r.a, r.b, r.c]) for r in sub.itertuples(index=False)}


def _eval(wf: pd.DataFrame, P: np.ndarray | None = None) -> dict:
    y = M.outcome_index(wf.hg, wf.ag)
    P = wf[["p_home", "p_draw", "p_away"]].to_numpy() if P is None else P
    return M.summary(P, y)


def tune(
    league: str, df: pd.DataFrame, grid: dict, tune_range: tuple[str, str], start: datetime
) -> tuple[RatingParams, list]:
    results = []
    keys = list(grid)
    for combo in itertools.product(*grid.values()):
        p = RatingParams(**dict(zip(keys, combo, strict=True)))
        wf = walk_forward(
            EngineConfig(league=league, params=p, use_context=False),
            start,
            end=datetime(int(tune_range[1][:4]) + 1, 1, 15)
            if league == "MLS"
            else datetime(int(tune_range[1][:4]) + 1, 7, 1),
            df=df,
        )
        wf = wf[wf.hg.notna() & (wf.season >= tune_range[0]) & (wf.season <= tune_range[1])]
        ll = M.log_loss(wf[["p_home", "p_draw", "p_away"]].to_numpy(), M.outcome_index(wf.hg, wf.ag))
        results.append({**dict(zip(keys, combo, strict=True)), "log_loss": ll, "n": len(wf)})
    results.sort(key=lambda r: r["log_loss"])
    best = {k: results[0][k] for k in keys}
    return RatingParams(**best), results


def leakage_audit(df: pd.DataFrame, params: RatingParams, honest: pd.DataFrame, q: pd.DataFrame) -> dict:
    """Refit ratings once per season *including that season's own results* and predict the same
    games. This is the classic in-sample mistake; the gap to the honest walk-forward is what a
    leaky backtest would have claimed."""
    played = df[df.hg.notna()].reset_index(drop=True)
    arrs = (
        played["kickoff"].to_numpy(dtype="datetime64[s]"),
        played["home_id"].to_numpy(),
        played["away_id"].to_numpy(),
        played["hg"].to_numpy(float),
        played["ag"].to_numpy(float),
        played["hxg"].to_numpy(float),
        played["axg"].to_numpy(float),
    )
    rows = []
    for _season, g in honest.groupby("season"):
        end = pd.to_datetime(g.kickoff).max().to_pydatetime()
        r = fit_ratings(end + pd.Timedelta(days=1), *arrs, params)
        for x in g.itertuples(index=False):
            lh, la = r.lambdas(x.home_id, x.away_id)
            ph, pd_, pa = outcome_probs(score_matrix(lh, la, x.rho))
            rows.append({**x._asdict(), "lh": lh, "la": la, "p_home": ph, "p_draw": pd_, "p_away": pa})
    leaky = pd.DataFrame(rows)
    st = Strategy("pinnacle close, edge>=3%", book="pinnacle", timing="close", min_edge=0.03)
    out = {}
    for name, frame in (("walk_forward", honest), ("in_sample_leak", leaky)):
        out[name] = {"metrics": _eval(frame), "betting": _strip(simulate(candidate_bets(frame, q, st), st))}
    return out


def _strip(sim: dict) -> dict:
    return {k: v for k, v in sim.items() if k != "curve"}


def _store_predictions(model: str, wf: pd.DataFrame) -> None:
    with session() as s:
        s.execute(delete(Prediction).where(Prediction.model == model))
        for r in wf.itertuples(index=False):
            s.add(
                Prediction(
                    match_id=int(r.id),
                    model=model,
                    as_of=pd.Timestamp(r.as_of).to_pydatetime(),
                    lam_h=float(r.lh),
                    lam_a=float(r.la),
                    rho=float(r.rho),
                    base_lam_h=float(r.base_lh),
                    base_lam_a=float(r.base_la),
                    p_home=float(r.p_home),
                    p_draw=float(r.p_draw),
                    p_away=float(r.p_away),
                    features={},
                )
            )
        s.commit()


def _save_kv(key: str, value: dict) -> None:
    with session() as s:
        row = s.get(KV, key)
        if row is None:
            s.add(KV(key=key, value=value))
        else:
            row.value = value
        s.commit()


def run_mls() -> dict:
    df = load_frame("MLS")
    q = _quotes("MLS")
    start = datetime(2014, 2, 1)
    params, grid = tune(
        "MLS",
        df,
        {"half_life_days": [120, 240, 400], "xg_weight": [0.0, 0.3, 0.6, 0.8, 1.0], "ridge": [2.0, 4.0, 8.0]},
        MLS_TUNE,
        start,
    )
    log.info("MLS tuned params: %s", params)
    variants = {
        "goals_only": EngineConfig(
            params=RatingParams(params.half_life_days, 0.0, params.ridge), use_context=False
        ),
        "xg_blend": EngineConfig(params=params, use_context=False),
        "xg_blend_context": EngineConfig(params=params, use_context=True),
    }
    wfs = {k: walk_forward(v, start, df=df) for k, v in variants.items()}
    final = wfs["xg_blend_context"]
    _store_predictions("mls_v1", final)

    pin = _market_probs(q, "pinnacle", "close")
    avg = _market_probs(q, "avg", "close")
    test_ids = set(final[(final.season >= MLS_TEST_FROM) & final.hg.notna()].id)
    common = sorted(test_ids & set(pin))  # same games for every row of the comparison table

    def sel(wf):
        return wf[wf.id.isin(common)].set_index("id").loc[common].reset_index()

    models = {k: _eval(sel(v)) for k, v in wfs.items()}
    base = sel(final)
    models["market_pinnacle_close"] = _eval(base, np.array([pin[i] for i in common]))
    models["market_average_close"] = (
        _eval(base, np.array([avg[i] for i in common])) if all(i in avg for i in common) else None
    )
    y = M.outcome_index(base.hg, base.ag)
    P = base[["p_home", "p_draw", "p_away"]].to_numpy()
    Pm = np.array([pin[i] for i in common])
    hits = np.eye(3)[y]
    calibration = {
        o: {"model": M.reliability(P[:, k], hits[:, k]), "market": M.reliability(Pm[:, k], hits[:, k])}
        for k, o in enumerate(("home", "draw", "away"))
    }

    test = final[(final.season >= MLS_TEST_FROM) & final.hg.notna()]
    xg_rows = test[test.hxg.notna()]
    goals_err = {
        "mae_goals_per_team": float(np.mean(np.abs(np.r_[test.lh - test.hg, test.la - test.ag]))),
        "mae_vs_xg_per_team": float(
            np.mean(np.abs(np.r_[xg_rows.lh - xg_rows.hxg, xg_rows.la - xg_rows.axg]))
        ),
        "mean_pred_total": float((test.lh + test.la).mean()),
        "mean_actual_total": float((test.hg + test.ag).mean()),
        "rmse_total": float(np.sqrt(np.mean(((test.lh + test.la) - (test.hg + test.ag)) ** 2))),
    }

    strategies = [
        Strategy("Pinnacle close, edge >= 3%", book="pinnacle", timing="close", min_edge=0.03),
        Strategy("Best price close (line shopping), edge >= 3%", book="best", timing="close", min_edge=0.03),
        Strategy("Best price close, edge >= 6%", book="best", timing="close", min_edge=0.06),
        Strategy(
            "Best price close, quarter-Kelly, edge >= 3%",
            book="best",
            timing="close",
            min_edge=0.03,
            staking="kelly",
        ),
        Strategy("Market average close, edge >= 3%", book="avg", timing="close", min_edge=0.03),
    ]
    betting = []
    best_cands = None
    for st in strategies:
        c = candidate_bets(test, q, st)
        if st.book == "best" and st.min_edge == 0.03 and st.staking == "flat":
            best_cands = c
        betting.append(simulate(c, st))
    edge_buckets = by_bucket(best_cands, "ev", [-1, 0, 0.03, 0.06, 0.1, 0.15, 0.25, 1.0])
    pos = best_cands[best_cands.ev >= 0.03]
    odds_buckets = by_bucket(pos, "price", [1.0, 1.8, 2.5, 3.5, 5.0, 100.0])

    seasons = []
    for season, g in test.groupby("season"):
        g2 = g[g.id.isin(pin)]
        if len(g2) == 0:
            continue
        yy = M.outcome_index(g2.hg, g2.ag)
        seasons.append(
            {
                "season": season,
                "n": int(len(g2)),
                "model_log_loss": M.log_loss(g2[["p_home", "p_draw", "p_away"]].to_numpy(), yy),
                "market_log_loss": M.log_loss(np.array([pin[i] for i in g2.id]), yy),
            }
        )
    seasons_no_pin = sorted(set(test.season) - {s["season"] for s in seasons})

    audit = leakage_audit(
        df, params, wfs["xg_blend"][wfs["xg_blend"].season >= MLS_TEST_FROM].query("hg == hg"), q
    )

    # live model for upcoming fixtures (stage 2 + rho trained on all OOS predictions)
    live = build_live_model("MLS", params, final[final.hg.notna()])
    _persist_live("MLS", live, params)

    return {
        "params": params.__dict__,
        "tuning": {"period": MLS_TUNE, "top": grid[:8], "combos": len(grid)},
        "test_period": f"{MLS_TEST_FROM}-{test.season.max()}",
        "n_test": int(len(test)),
        "n_compare": len(common),
        "models": models,
        "calibration": calibration,
        "goals": goals_err,
        "betting": betting,
        "edge_buckets": edge_buckets,
        "odds_buckets": odds_buckets,
        "by_season": seasons,
        "seasons_without_pinnacle": seasons_no_pin,
        "leakage_audit": audit,
        "draws": {
            "predicted": float(P[:, 1].mean()),
            "observed": float(hits[:, 1].mean()),
            "rho": float(final.rho.iloc[-1]),
        },
    }


def run_epl() -> dict:
    df = load_frame("EPL")
    q = _quotes("EPL")
    start = datetime(2016, 7, 1)
    params, grid = tune(
        "EPL", df, {"half_life_days": [120, 240, 400], "ridge": [1.0, 2.0, 4.0]}, EPL_TUNE, start
    )
    params.xg_weight = 0.0
    wf = walk_forward(EngineConfig(league="EPL", params=params, use_context=False), start, df=df)
    wf = wf[wf.hg.notna()]

    # market-implied expected goals from the OPENING Pinnacle 1X2 (known at decision time)
    pin_open = _market_probs(q, "pinnacle", "open")
    pin_close = _market_probs(q, "pinnacle", "close")
    wf = wf[wf.id.isin(pin_open)].copy()
    mk = [lambdas_from_1x2(pin_open[i][0], pin_open[i][2], r) for i, r in zip(wf.id, wf.rho, strict=True)]
    wf["mlh"], wf["mla"] = [x[0] for x in mk], [x[1] for x in mk]

    def pooled(frame, w):
        f = frame.copy()
        f["lh"] = np.exp(w * np.log(f.lh) + (1 - w) * np.log(f.mlh))
        f["la"] = np.exp(w * np.log(f.la) + (1 - w) * np.log(f.mla))
        pr = [outcome_probs(score_matrix(a, b, r)) for a, b, r in zip(f.lh, f.la, f.rho, strict=True)]
        f[["p_home", "p_draw", "p_away"]] = np.array(pr)
        return f

    tune_rows = wf[(wf.season >= EPL_TUNE[0]) & (wf.season <= EPL_TUNE[1])]
    w_scores = {w: _eval(pooled(tune_rows, w))["log_loss"] for w in np.round(np.arange(0, 1.01, 0.1), 2)}
    w_best = float(min(w_scores, key=w_scores.get))
    test = wf[wf.season >= EPL_TEST_FROM]
    blend = pooled(test, w_best)
    _store_predictions("epl_v1", wf)

    common = [i for i in test.id if i in pin_close]
    t2 = test.set_index("id").loc[common].reset_index()
    models = {
        "model_goals_dixon_coles": _eval(t2),
        f"pooled_with_open_market_w{w_best}": _eval(blend.set_index("id").loc[common].reset_index()),
        "market_pinnacle_open": _eval(t2, np.array([pin_open[i] for i in common])),
        "market_pinnacle_close": _eval(t2, np.array([pin_close[i] for i in common])),
    }
    betting = []
    for frame_name, frame in (("model", test), ("pooled", blend)):
        for market in ("1x2", "ah", "ou"):
            st = Strategy(
                f"EPL {market.upper()} {frame_name}: Pinnacle open, edge >= 3%, CLV vs Pinnacle close",
                market=market,
                book="pinnacle",
                timing="open",
                min_edge=0.03,
                clv_book="pinnacle",
            )
            betting.append(simulate(candidate_bets(frame, q, st), st))
    rho = fit_rho(test.lh, test.la, test.hg, test.ag)
    return {
        "params": params.__dict__,
        "tuning": {"period": EPL_TUNE, "top": grid[:5]},
        "pool_weight_model": w_best,
        "pool_weight_scores": {str(k): v for k, v in w_scores.items()},
        "test_period": f"{EPL_TEST_FROM} to {test.season.max()}",
        "n_compare": len(common),
        "models": models,
        "betting": betting,
        "rho": rho,
    }


def _persist_live(league: str, live, params: RatingParams) -> None:
    payload = {
        "league": league,
        "as_of": live.as_of.isoformat(),
        "params": params.__dict__,
        "rho": live.rho,
        "ratings": {
            "mu": live.ratings.mu,
            "home": live.ratings.home,
            "attack": live.ratings.attack,
            "defence": live.ratings.defence,
            "n_obs": live.ratings.n_obs,
        },
        "context_model": live.context.booster.model_to_string()
        if live.context and live.context.booster
        else None,
    }
    _save_kv(f"live_model:{league}", payload)


def run_all() -> dict:
    t0 = datetime.now(UTC)
    with session() as s:
        n_mls = s.scalar(select(func.count()).select_from(Match).where(Match.league == "MLS"))
    report = {
        "generated_at": t0.isoformat(),
        "mls": run_mls(),
        "epl": run_epl(),
        "data": {"mls_matches": n_mls},
    }
    report["runtime_seconds"] = (datetime.now(UTC) - t0).total_seconds()
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    path = settings.reports_dir / "backtest.json"
    path.write_text(json.dumps(report, indent=1, default=str))
    _save_kv("backtest_report_meta", {"path": str(path), "generated_at": report["generated_at"]})
    log.info("backtest report written to %s", path)
    return report
