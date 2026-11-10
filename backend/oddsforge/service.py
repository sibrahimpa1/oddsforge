"""Read-side service: point-in-time predictions, market prices and value assessment for a match.

Two modes:
- live: upcoming MLS fixtures, priced by the live model (ratings fitted on everything up to
  now), optional lineup absences, odds from the latest snapshots (ESPN / The Odds API).
- replay: any historical match, priced by the *walk-forward* prediction stored by the backtest
  (only information before that week), odds = closing prices. Scores stay hidden until the
  player "kicks off" the matchday.
"""

from __future__ import annotations

import functools
import math
from datetime import datetime, timedelta

import lightgbm as lgb
import numpy as np
import pandas as pd
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .db import KV, Match, OddsQuote, Prediction
from .markets.derive import asian_breakdown, effective_prob, ev_from_breakdown, market_ladder, total_breakdown
from .markets.odds import devig, kelly_fraction, overround
from .model.context import build_context
from .model.dixon_coles import score_matrix
from .model.engine import ContextModel, LiveModel, load_frame
from .model.lineup import apply_absences, team_player_values
from .model.ratings import Ratings
from .teams import get_team

MIN_EDGE = 0.03
MAX_EDGE = 0.25
REPLAY_BOOKS = ["avg", "pinnacle", "bet365", "best"]  # a typical book first; "best" is line shopping
MODEL_FOR = {"MLS": "mls_v1", "EPL": "epl_v1"}


def team_label(team_id: str) -> dict:
    t = get_team(team_id)
    if t:
        return {"id": t.id, "name": t.name, "short": t.short, "conference": t.conference}
    name = team_id.replace("-", " ").title()
    return {"id": team_id, "name": name, "short": name, "conference": ""}


def local_day(m: Match) -> str:
    """Matchday key: US Eastern date for MLS (evening kickoffs cross midnight UTC), UK date otherwise."""
    shift = -5 if m.league == "MLS" else 0
    return (m.kickoff + timedelta(hours=shift)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- live model


@functools.lru_cache(maxsize=4)
def _live_model_cached(league: str, stamp: str) -> LiveModel | None:
    from .db import session

    with session() as s:
        kv = s.get(KV, f"live_model:{league}")
    if kv is None:
        return None
    v = kv.value
    r = v["ratings"]
    ratings = Ratings(
        as_of=datetime.fromisoformat(v["as_of"]),
        mu=r["mu"],
        home=r["home"],
        attack=r["attack"],
        defence=r["defence"],
        n_obs=r.get("n_obs", {}),
    )
    cm = None
    if v.get("context_model"):
        cm = ContextModel()
        cm.booster = lgb.Booster(model_str=v["context_model"])
    ctx = build_context(load_frame(league)).set_index("id") if cm is not None else None
    return LiveModel(league, ratings, cm, v["rho"], ctx, ratings.as_of)


def live_model(s: Session, league: str = "MLS") -> LiveModel | None:
    kv = s.get(KV, f"live_model:{league}")
    if kv is None:
        return None
    return _live_model_cached(league, kv.updated_at.isoformat())


# ---------------------------------------------------------------- prices


def _latest_quotes(m: Match, mode: str) -> list[OddsQuote]:
    if mode == "replay":
        return [q for q in m.odds if q.timing == "close"]
    snaps = [q for q in m.odds if q.timing == "snapshot"]
    latest: dict[tuple, OddsQuote] = {}
    for q in snaps:
        k = (q.market, q.book, q.line)
        if k not in latest or (q.captured_at or datetime.min) > (latest[k].captured_at or datetime.min):
            latest[k] = q
    return list(latest.values())


HOUSE_MARGIN = 0.05


def _house_prices(s: Session, m: Match, mode: str, board: dict) -> None:
    """Fill markets that have no real bookmaker price with the OddsForge house book: the model's
    own fair price with a 5% margin. Labelled everywhere as "house"; never counts as value."""
    missing = [k for k, v in board.items() if not v]
    if not missing:
        return
    pred = prediction(s, m, mode)
    if pred is None:
        return
    lad = pred["ladder"]

    def px(p: float) -> float:
        return round(max(1.01, 1 / (p * (1 + HOUSE_MARGIN))), 2)

    if "1x2" in missing:
        for sel in ("home", "draw", "away"):
            p = lad["1x2"][sel]
            board["1x2"].append(
                {
                    "selection": sel,
                    "line": None,
                    "price": px(p),
                    "book": "house",
                    "fair_prob": p,
                    "margin": HOUSE_MARGIN,
                    "captured_at": None,
                }
            )
    if "ah" in missing:
        main = min(lad["asian_handicap"], key=lambda r: abs(r["home_prob"] - 0.5))
        for sel in ("home", "away"):
            p = main[f"{sel}_prob"]
            board["ah"].append(
                {
                    "selection": sel,
                    "line": main["line"],
                    "price": px(p),
                    "book": "house",
                    "fair_prob": p,
                    "margin": HOUSE_MARGIN,
                    "captured_at": None,
                }
            )
    if "ou" in missing:
        for row in [r for r in lad["totals"] if r["line"] in (2.5, 3.5)]:
            for sel in ("over", "under"):
                p = row[f"{sel}_prob"]
                board["ou"].append(
                    {
                        "selection": sel,
                        "line": row["line"],
                        "price": px(p),
                        "book": "house",
                        "fair_prob": p,
                        "margin": HOUSE_MARGIN,
                        "captured_at": None,
                    }
                )


def price_board(m: Match, mode: str, s: Session | None = None) -> dict:
    """Bettable prices. Replay: one typical book per market (closing). Live: best price per
    selection across books (line shopping), with the book named. With a session, markets with
    no real price get house prices."""
    board = _real_board(m, mode)
    if s is not None:
        _house_prices(s, m, mode, board)
    return board


def _real_board(m: Match, mode: str) -> dict:
    quotes = _latest_quotes(m, mode)
    board: dict[str, list[dict]] = {"1x2": [], "ah": [], "ou": []}
    for market in board:
        qs = [q for q in quotes if q.market == market]
        if not qs:
            continue
        if mode == "replay":
            by_book = {q.book: q for q in qs}
            book = next((b for b in REPLAY_BOOKS if b in by_book), None)
            if book is None:
                continue
            chosen = [by_book[book]]
        else:
            chosen = qs
        sels = (
            ("home", "draw", "away")
            if market == "1x2"
            else (("home", "away") if market == "ah" else ("over", "under"))
        )
        best: dict[tuple, dict] = {}
        for q in chosen:
            prices = [q.price_a, q.price_b, q.price_c] if market == "1x2" else [q.price_a, q.price_b]
            if any(p is None or p <= 1 for p in prices):
                continue
            fair = devig(prices)
            for sel, p, f in zip(sels, prices, fair, strict=True):
                key = (sel, q.line)
                if key not in best or p > best[key]["price"]:
                    best[key] = {
                        "selection": sel,
                        "line": q.line,
                        "price": p,
                        "book": q.book,
                        "fair_prob": f,
                        "margin": overround(prices),
                        "captured_at": q.captured_at.isoformat() if q.captured_at else None,
                    }
        board[market] = list(best.values())
    return board


def lookup_price(
    s: Session, m: Match, mode: str, market: str, selection: str, line: float | None
) -> dict | None:
    for row in price_board(m, mode, s).get(market, []):
        if row["selection"] == selection and (
            line is None or row["line"] is None or math.isclose(row["line"], line)
        ):
            return row
    return None


# ---------------------------------------------------------------- predictions


def prediction(s: Session, m: Match, mode: str, absent: list[str] | None = None) -> dict | None:
    absent = absent or []
    lineup = None
    context = {}
    if mode == "live":
        lm = live_model(s, m.league)
        if lm is None:
            return None
        p = lm.predict(m.id, m.home_id, m.away_id)
        lh, la, rho, base_lh, base_la, context = (
            p["lh"],
            p["la"],
            p["rho"],
            p["base_lh"],
            p["base_la"],
            p["context"],
        )
        as_of = lm.as_of
        if absent:
            hv, av = team_player_values(m.home_id), team_player_values(m.away_id)
            ho = [x for x in hv if x.player_id in absent]
            ao = [x for x in av if x.player_id in absent]
            lh, la, lineup = apply_absences(lh, la, ho, ao)
            lineup["absent"] = [x.name for x in ho + ao]
        model_name = f"live:{m.league}"
    else:
        pr = s.scalar(
            select(Prediction).where(Prediction.match_id == m.id, Prediction.model == MODEL_FOR[m.league])
        )
        if pr is None:
            return None
        lh, la, rho, base_lh, base_la, as_of = (
            pr.lam_h,
            pr.lam_a,
            pr.rho,
            pr.base_lam_h,
            pr.base_lam_a,
            pr.as_of,
        )
        model_name = pr.model
    mat = score_matrix(lh, la, rho)
    ladder = market_ladder(mat)
    return {
        "model": model_name,
        "as_of": as_of.isoformat(),
        "lam_h": lh,
        "lam_a": la,
        "rho": rho,
        "base_lam_h": base_lh,
        "base_lam_a": base_la,
        "ladder": ladder,
        "context": context,
        "lineup": lineup,
        "_matrix": mat,
    }


def value_rows(pred: dict, board: dict) -> list[dict]:
    """Model vs market for every bettable selection, with an explicit bet / pass verdict."""
    mat = pred["_matrix"]
    x = pred["ladder"]["1x2"]
    rows = []
    for market, items in board.items():
        for it in items:
            price = it["price"]
            if market == "1x2":
                prob = x[it["selection"]]
                ev = prob * price - 1
            else:
                bd = (
                    asian_breakdown(mat, it["line"], it["selection"])
                    if market == "ah"
                    else total_breakdown(mat, it["line"], it["selection"])
                )
                prob = effective_prob(bd)
                ev = ev_from_breakdown(bd, price)
            if it["book"] == "house":
                verdict, why = (
                    "house",
                    "house price = model price minus a 5% margin (no real bookmaker price yet)",
                )
            elif ev < MIN_EDGE:
                verdict, why = "pass", "below the 3% minimum edge"
            elif ev > MAX_EDGE:
                verdict, why = (
                    "caution",
                    "edge this large usually means the model is missing news (lineups, injuries)",
                )
            else:
                verdict, why = "value", "model price beats the market by more than the threshold"
            rows.append(
                {
                    "market": market,
                    "selection": it["selection"],
                    "line": it["line"],
                    "price": price,
                    "book": it["book"],
                    "model_prob": prob,
                    "market_prob": it["fair_prob"],
                    "fair_price": 1 / prob if prob > 0 else None,
                    "ev": ev,
                    "verdict": verdict,
                    "why": why,
                    "kelly_stake_pct": kelly_fraction((1 + ev) / price, price) * 100
                    if verdict == "value"
                    else 0.0,
                }
            )
    return sorted(rows, key=lambda r: -r["ev"])


# ---------------------------------------------------------------- form / h2h


def form(s: Session, team_id: str, before: datetime, n: int = 5, league: str = "MLS") -> list[dict]:
    rows = s.scalars(
        select(Match)
        .where(
            Match.league == league,
            Match.kickoff < before,
            Match.status == "final",
            or_(Match.home_id == team_id, Match.away_id == team_id),
        )
        .order_by(Match.kickoff.desc())
        .limit(n)
    ).all()
    out = []
    for m in rows:
        home = m.home_id == team_id
        gf, ga = (m.home_goals, m.away_goals) if home else (m.away_goals, m.home_goals)
        xf, xa = (m.home_xg, m.away_xg) if home else (m.away_xg, m.home_xg)
        out.append(
            {
                "date": m.kickoff.strftime("%Y-%m-%d"),
                "opponent": team_label(m.away_id if home else m.home_id)["short"],
                "venue": "H" if home else "A",
                "gf": gf,
                "ga": ga,
                "xgf": xf,
                "xga": xa,
                "result": "W" if gf > ga else ("D" if gf == ga else "L"),
            }
        )
    return out


def h2h(s: Session, m: Match, n: int = 6) -> list[dict]:
    rows = s.scalars(
        select(Match)
        .where(
            Match.league == m.league,
            Match.kickoff < m.kickoff,
            Match.status == "final",
            or_(
                and_(Match.home_id == m.home_id, Match.away_id == m.away_id),
                and_(Match.home_id == m.away_id, Match.away_id == m.home_id),
            ),
        )
        .order_by(Match.kickoff.desc())
        .limit(n)
    ).all()
    return [
        {
            "date": r.kickoff.strftime("%Y-%m-%d"),
            "home": team_label(r.home_id)["short"],
            "away": team_label(r.away_id)["short"],
            "score": f"{r.home_goals}-{r.away_goals}",
            "xg": f"{r.home_xg:.2f}-{r.away_xg:.2f}" if r.home_xg is not None else None,
        }
        for r in rows
    ]


def lineup_options(team_id: str, limit: int = 14) -> list[dict]:
    return [
        {
            "player_id": p.player_id,
            "name": p.name,
            "position": p.position,
            "minutes": p.minutes,
            "minutes_share": round(p.minutes_share, 2),
            "attack_loss_pct": round(p.attack_loss * 100, 1),
            "defence_loss": round(p.defence_loss + p.gk_loss, 3),
            "replacement": p.replacement,
        }
        for p in team_player_values(team_id)[:limit]
    ]


def ratings_table(s: Session, league: str = "MLS") -> list[dict]:
    lm = live_model(s, league)
    if lm is None:
        return []
    r = lm.ratings
    active = {
        m.home_id
        for m in s.scalars(
            select(Match).where(Match.league == league, Match.kickoff > lm.as_of - timedelta(days=200))
        )
    }
    rows = []
    for row in r.table():
        if row["team"] not in active:
            continue
        # expected goals per game against a league-average opponent at a neutral venue
        xgf = float(np.exp(r.mu + r.home / 2 + row["attack"]))
        xga = float(np.exp(r.mu + r.home / 2 - row["defence"]))
        rows.append(
            {
                **team_label(row["team"]),
                "attack": row["attack"],
                "defence": row["defence"],
                "net": row["net"],
                "xg_for": xgf,
                "xg_against": xga,
            }
        )
    return rows


def frame_to_records(df: pd.DataFrame) -> list[dict]:
    return df.replace({np.nan: None}).to_dict("records")
