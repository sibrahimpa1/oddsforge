"""Walk-forward prediction engine.

Decision points are weekly. At each decision time T the engine:
1. fits team ratings on matches that kicked off strictly before T,
2. predicts every match in [T, T + 7 days) from those ratings (stage 1, "base" expected goals),
3. applies the context model (stage 2), which is retrained once per season on earlier
   seasons' *out-of-sample* stage-1 predictions, never on in-sample fits,
4. turns expected goals into a Dixon-Coles score matrix with a rho fitted on earlier seasons.

No market price is a model input. Odds only enter later, in the betting layer, which is what
lets the backtest compare model and market honestly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import lightgbm as lgb
import numpy as np
import pandas as pd
from sqlalchemy import select

from ..db import Match, session
from .context import FEATURES, build_context, side_matrix
from .dixon_coles import fit_rho, outcome_probs, score_matrix
from .ratings import RatingParams, Ratings, fit_ratings

log = logging.getLogger(__name__)

DEFAULT_RHO = -0.05


@dataclass
class EngineConfig:
    league: str = "MLS"
    params: RatingParams = field(default_factory=RatingParams)
    use_context: bool = True
    refit_days: int = 7
    min_context_seasons: int = 2


def load_frame(league: str) -> pd.DataFrame:
    with session() as s:
        rows = s.execute(
            select(
                Match.id,
                Match.season,
                Match.kickoff,
                Match.home_id,
                Match.away_id,
                Match.home_goals,
                Match.away_goals,
                Match.home_xg,
                Match.away_xg,
                Match.knockout,
                Match.status,
            )
            .where(Match.league == league)
            .order_by(Match.kickoff)
        ).all()
    df = pd.DataFrame(
        rows,
        columns=[
            "id",
            "season",
            "kickoff",
            "home_id",
            "away_id",
            "hg",
            "ag",
            "hxg",
            "axg",
            "knockout",
            "status",
        ],
    )
    df["kickoff"] = pd.to_datetime(df["kickoff"])
    df["hxg"] = df["hxg"].astype(float)
    df["axg"] = df["axg"].astype(float)
    return df


class ContextModel:
    """LightGBM Poisson model that *adjusts* stage-1 expected goals. Ratings enter as the
    offset (init_score), so trees can only learn what the ratings miss, and the output stays a
    goal rate that feeds the same score matrix (no separate 1X2 classifier to contradict it)."""

    PARAMS = dict(
        objective="poisson",
        learning_rate=0.03,
        num_leaves=7,
        min_data_in_leaf=150,
        feature_fraction=0.8,
        bagging_fraction=0.8,
        bagging_freq=1,
        lambda_l2=10.0,
        verbose=-1,
        seed=7,
    )

    def __init__(self, rounds: int = 120):
        self.rounds = rounds
        self.booster: lgb.Booster | None = None

    def fit(self, X: np.ndarray, base_lam: np.ndarray, goals: np.ndarray) -> ContextModel:
        ds = lgb.Dataset(
            X, label=goals, init_score=np.log(base_lam), feature_name=FEATURES, free_raw_data=False
        )
        self.booster = lgb.train(self.PARAMS, ds, num_boost_round=self.rounds)
        return self

    def multiplier(self, X: np.ndarray) -> np.ndarray:
        if self.booster is None:
            return np.ones(len(X))
        return np.exp(self.booster.predict(X, raw_score=True))

    def contributions(self, X: np.ndarray) -> np.ndarray:
        """Per-feature log-rate contributions (SHAP values from LightGBM's TreeSHAP)."""
        if self.booster is None:
            return np.zeros((len(X), len(FEATURES) + 1))
        return self.booster.predict(X, pred_contrib=True)


def _arrays(df: pd.DataFrame):
    return (
        df["kickoff"].to_numpy(dtype="datetime64[s]"),
        df["home_id"].to_numpy(),
        df["away_id"].to_numpy(),
        df["hg"].to_numpy(dtype=float),
        df["ag"].to_numpy(dtype=float),
        df["hxg"].to_numpy(dtype=float),
        df["axg"].to_numpy(dtype=float),
    )


def walk_forward(
    cfg: EngineConfig, start: datetime, end: datetime | None = None, df: pd.DataFrame | None = None
) -> pd.DataFrame:
    df = load_frame(cfg.league) if df is None else df
    played = df[df["hg"].notna()].reset_index(drop=True)
    ctx = build_context(df).set_index("id") if cfg.use_context else None
    arrs = _arrays(played)
    end = end or df["kickoff"].max().to_pydatetime() + timedelta(days=1)

    out: list[dict] = []
    t = start
    prev: Ratings | None = None
    season_models: dict[str, tuple[ContextModel | None, float]] = {}
    while t < end:
        t_next = t + timedelta(days=cfg.refit_days)
        week = df[(df["kickoff"] >= t) & (df["kickoff"] < t_next)]
        if len(week):
            try:
                prev = fit_ratings(t, *arrs, cfg.params, prev=prev)
            except ValueError:
                t = t_next
                continue
            past = pd.DataFrame(out)
            for r in week.itertuples(index=False):
                if r.season not in season_models:  # retrain stage 2 + rho once per season, on past OOS rows
                    season_models[r.season] = _season_models(cfg, past, played, ctx, t)
                cm, rho = season_models[r.season]
                bh, ba = prev.lambdas(r.home_id, r.away_id)
                lh, la = bh, ba
                if cm is not None and ctx is not None:
                    c = ctx.loc[[r.id]]
                    lh = float(bh * cm.multiplier(side_matrix(c, "h"))[0])
                    la = float(ba * cm.multiplier(side_matrix(c, "a"))[0])
                ph, pd_, pa = outcome_probs(score_matrix(lh, la, rho))
                out.append(
                    {
                        "id": r.id,
                        "season": r.season,
                        "kickoff": r.kickoff,
                        "as_of": t,
                        "home_id": r.home_id,
                        "away_id": r.away_id,
                        "base_lh": bh,
                        "base_la": ba,
                        "lh": lh,
                        "la": la,
                        "rho": rho,
                        "p_home": ph,
                        "p_draw": pd_,
                        "p_away": pa,
                        "hg": r.hg,
                        "ag": r.ag,
                        "hxg": r.hxg,
                        "axg": r.axg,
                        "knockout": r.knockout,
                    }
                )
        t = t_next
    res = pd.DataFrame(out)
    assert (pd.to_datetime(res["as_of"]) <= pd.to_datetime(res["kickoff"])).all(), "look-ahead detected"
    return res


def _season_models(cfg: EngineConfig, past: pd.DataFrame, played: pd.DataFrame, ctx, t: datetime):
    if past.empty:
        return None, DEFAULT_RHO
    hist = past[past["hg"].notna() & (pd.to_datetime(past["kickoff"]) < t)]
    rho = fit_rho(hist["lh"], hist["la"], hist["hg"], hist["ag"]) if len(hist) > 500 else DEFAULT_RHO
    if not cfg.use_context or ctx is None or hist["season"].nunique() < cfg.min_context_seasons:
        return None, rho
    c = ctx.loc[hist["id"]]
    X = np.vstack([side_matrix(c, "h"), side_matrix(c, "a")])
    base = np.r_[hist["base_lh"].to_numpy(), hist["base_la"].to_numpy()]
    goals = np.r_[hist["hg"].to_numpy(), hist["ag"].to_numpy()]
    # rho was fitted on stage-1+2 lambdas of earlier seasons; keep it (refit per season)
    return ContextModel().fit(X, base, goals), rho


@dataclass
class LiveModel:
    """Everything needed to price an upcoming match right now."""

    league: str
    ratings: Ratings
    context: ContextModel | None
    rho: float
    ctx_frame: pd.DataFrame | None
    as_of: datetime

    def base(self, home: str, away: str) -> tuple[float, float]:
        return self.ratings.lambdas(home, away)

    def predict(self, match_id: int, home: str, away: str) -> dict:
        bh, ba = self.base(home, away)
        lh, la, contrib = bh, ba, {}
        if self.context is not None and self.ctx_frame is not None and match_id in self.ctx_frame.index:
            c = self.ctx_frame.loc[[match_id]]
            xh, xa = side_matrix(c, "h"), side_matrix(c, "a")
            lh = float(bh * self.context.multiplier(xh)[0])
            la = float(ba * self.context.multiplier(xa)[0])
            ch, ca = self.context.contributions(xh)[0], self.context.contributions(xa)[0]
            contrib = {
                f: {
                    "home": float(ch[i]),
                    "away": float(ca[i]),
                    "value_home": float(xh[0, i]),
                    "value_away": float(xa[0, i]),
                }
                for i, f in enumerate(FEATURES)
            }
        return {"base_lh": bh, "base_la": ba, "lh": lh, "la": la, "rho": self.rho, "context": contrib}


def build_live_model(
    league: str, params: RatingParams, wf: pd.DataFrame | None, use_context: bool = True
) -> LiveModel:
    """Fit on all completed matches. Stage 2 and rho are trained on the walk-forward (out-of-sample)
    predictions, exactly as in the backtest."""
    df = load_frame(league)
    played = df[df["hg"].notna()].reset_index(drop=True)
    now = datetime.utcnow()
    as_of = min(now, df["kickoff"].max().to_pydatetime() + timedelta(days=1))
    ratings = fit_ratings(as_of, *_arrays(played), params)
    ctx = build_context(df).set_index("id") if use_context else None
    cm, rho = None, DEFAULT_RHO
    if wf is not None and len(wf):
        hist = wf[wf["hg"].notna()]
        rho = fit_rho(hist["lh"], hist["la"], hist["hg"], hist["ag"])
        if use_context and ctx is not None:
            c = ctx.loc[hist["id"]]
            X = np.vstack([side_matrix(c, "h"), side_matrix(c, "a")])
            base = np.r_[hist["base_lh"].to_numpy(), hist["base_la"].to_numpy()]
            goals = np.r_[hist["hg"].to_numpy(), hist["ag"].to_numpy()]
            cm = ContextModel().fit(X, base, goals)
    return LiveModel(league, ratings, cm, rho, ctx, as_of)
