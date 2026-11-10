"""HTTP API (FastAPI). Run: uvicorn oddsforge.api:app --reload"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import analyst
from .betting import service as bets
from .config import settings
from .db import KV, Bet, Match, Prediction, User, session, utcnow
from .service import (
    MODEL_FOR,
    form,
    h2h,
    lineup_options,
    local_day,
    prediction,
    price_board,
    ratings_table,
    team_label,
    value_rows,
)

log = logging.getLogger(__name__)
REFRESH_MINUTES = int(os.getenv("ODDSFORGE_REFRESH_MINUTES", "30"))


async def _scheduler():
    """Refresh fixtures/results/odds and settle bets on a schedule (skipped when offline)."""
    from .etl.load import load_espn, load_odds_api
    from .etl.sources import _client, fetch_espn, fetch_odds_api

    while True:
        await asyncio.sleep(REFRESH_MINUTES * 60)
        try:

            def tick():
                with _client() as c:
                    fetch_espn(c, days_back=7, days_ahead=30)
                    fetch_odds_api(c)
                with session() as s:
                    load_espn(s)
                    load_odds_api(s)
                    s.commit()
                    return bets.settle_live(s)

            n = await asyncio.to_thread(tick)
            log.info("scheduled refresh done, settled %d bets", n)
        except Exception as exc:
            log.warning("scheduled refresh failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = None
    if not settings.offline and os.getenv("ODDSFORGE_SCHEDULER", "1") == "1":
        task = asyncio.create_task(_scheduler())
    yield
    if task:
        task.cancel()


app = FastAPI(title="OddsForge API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)


def db():
    s = session()
    try:
        yield s
    finally:
        s.close()


def current_user(x_player_token: str | None = Header(default=None), s: Session = Depends(db)) -> User:
    u = bets.user_by_token(s, x_player_token)
    if u is None:
        raise HTTPException(401, "create a player first (POST /api/players)")
    return u


def _mode_for(m: Match) -> str:
    return "replay" if m.status == "final" else "live"


def match_card(s: Session, m: Match, mode: str, reveal: bool) -> dict:
    pred = prediction(s, m, mode)
    board = price_board(m, mode, s)
    vals = value_rows(pred, board) if pred else []
    best = next((v for v in vals if v["verdict"] == "value"), None)
    return {
        "id": m.id,
        "league": m.league,
        "season": m.season,
        "kickoff": m.kickoff.isoformat() + "Z",
        "day": local_day(m),
        "status": m.status,
        "stage": m.stage,
        "knockout": m.knockout,
        "venue": m.venue,
        "home": team_label(m.home_id),
        "away": team_label(m.away_id),
        "score": {"home": m.home_goals, "away": m.away_goals, "home_xg": m.home_xg, "away_xg": m.away_xg}
        if reveal
        else None,
        "prediction": {
            "xg_home": pred["ladder"]["xg_home"],
            "xg_away": pred["ladder"]["xg_away"],
            "p": pred["ladder"]["1x2"],
        }
        if pred
        else None,
        "prices_1x2": {r["selection"]: {"price": r["price"], "book": r["book"]} for r in board["1x2"]},
        "markets_available": [k for k, v in board.items() if v],
        "best_value": best,
    }


@app.get("/api/health")
def health(s: Session = Depends(db)):
    n = s.scalar(select(func.count()).select_from(Match))
    live = s.get(KV, "live_model:MLS")
    return {
        "ok": True,
        "matches": n,
        "live_model_as_of": live.value["as_of"] if live else None,
        "claude": bool(settings.anthropic_api_key),
        "odds_api": bool(settings.odds_api_key),
        "offline": settings.offline,
    }


@app.get("/api/matches/upcoming")
def upcoming(s: Session = Depends(db)):
    now = utcnow() - timedelta(hours=3)
    ms = s.scalars(
        select(Match)
        .where(Match.league == "MLS", Match.status.in_(["scheduled", "live"]), Match.kickoff >= now)
        .order_by(Match.kickoff)
        .limit(40)
    ).all()
    recent = s.scalars(
        select(Match)
        .where(
            Match.league == "MLS",
            Match.espn_id.is_not(None),
            Match.status == "final",
            Match.kickoff >= utcnow() - timedelta(days=10),
        )
        .order_by(Match.kickoff.desc())
        .limit(12)
    ).all()
    return {
        "upcoming": [match_card(s, m, "live", False) for m in ms],
        "recent_results": [
            {
                "id": m.id,
                "kickoff": m.kickoff.isoformat() + "Z",
                "home": team_label(m.home_id),
                "away": team_label(m.away_id),
                "score": f"{m.home_goals}-{m.away_goals}",
            }
            for m in recent
        ],
    }


@app.get("/api/replay/seasons")
def replay_seasons(league: str = "MLS", s: Session = Depends(db)):
    rows = s.execute(
        select(Match.season, func.count())
        .join(Prediction, Prediction.match_id == Match.id)
        .where(Match.league == league, Prediction.model == MODEL_FOR[league])
        .group_by(Match.season)
        .order_by(Match.season.desc())
    ).all()
    return [{"season": r[0], "matches": r[1]} for r in rows]


@app.get("/api/replay/matchdays")
def replay_matchdays(
    league: str = "MLS",
    season: str = Query(...),
    x_player_token: str | None = Header(default=None),
    s: Session = Depends(db),
):
    user = bets.user_by_token(s, x_player_token)
    revealed = bets.revealed_days(s, user) if user else set()
    ms = s.scalars(
        select(Match)
        .join(Prediction, Prediction.match_id == Match.id)
        .where(Match.league == league, Match.season == season, Prediction.model == MODEL_FOR[league])
        .order_by(Match.kickoff)
    ).all()
    days: dict[str, int] = {}
    for m in ms:
        days[local_day(m)] = days.get(local_day(m), 0) + 1
    return [{"day": d, "matches": n, "revealed": f"{league}:{d}" in revealed} for d, n in days.items()]


@app.get("/api/replay/day")
def replay_day(
    league: str = "MLS",
    day: str = Query(...),
    x_player_token: str | None = Header(default=None),
    s: Session = Depends(db),
):
    user = bets.user_by_token(s, x_player_token)
    revealed = f"{league}:{day}" in (bets.revealed_days(s, user) if user else set())
    ms = s.scalars(
        select(Match)
        .join(Prediction, Prediction.match_id == Match.id)
        .where(
            Match.league == league,
            Prediction.model == MODEL_FOR[league],
            Match.kickoff >= datetime.fromisoformat(day) - timedelta(hours=12),
            Match.kickoff <= datetime.fromisoformat(day) + timedelta(hours=40),
        )
        .order_by(Match.kickoff)
    ).all()
    ms = [m for m in ms if local_day(m) == day]
    return {
        "league": league,
        "day": day,
        "revealed": revealed,
        "matches": [match_card(s, m, "replay", revealed) for m in ms],
    }


@app.get("/api/matches/{match_id}")
def match_detail(
    match_id: int,
    absent: str = "",
    x_player_token: str | None = Header(default=None),
    s: Session = Depends(db),
):
    m = s.get(Match, match_id)
    if m is None:
        raise HTTPException(404)
    mode = _mode_for(m)
    user = bets.user_by_token(s, x_player_token)
    reveal = mode == "live" or (user is not None and bets.day_key(m) in bets.revealed_days(s, user))
    absent_ids = [a for a in absent.split(",") if a]
    pred = prediction(s, m, mode, absent_ids if mode == "live" else None)
    board = price_board(m, mode, s)
    card = match_card(s, m, mode, reveal and m.status == "final")
    out = {
        **card,
        "mode": mode,
        "form": {
            "home": form(s, m.home_id, m.kickoff, league=m.league),
            "away": form(s, m.away_id, m.kickoff, league=m.league),
        },
        "h2h": h2h(s, m),
        "board": board,
    }
    if pred:
        out["model"] = {k: v for k, v in pred.items() if not k.startswith("_")}
        out["values"] = value_rows(pred, board)
    if mode == "live" and m.league == "MLS":
        out["lineup_options"] = {"home": lineup_options(m.home_id), "away": lineup_options(m.away_id)}
    return out


class AnalysisIn(BaseModel):
    absent: list[str] = Field(default_factory=list)


@app.post("/api/matches/{match_id}/analysis")
def match_analysis(match_id: int, body: AnalysisIn, s: Session = Depends(db)):
    m = s.get(Match, match_id)
    if m is None:
        raise HTTPException(404)
    mode = _mode_for(m)
    pred = prediction(s, m, mode, body.absent if mode == "live" else None)
    if pred is None:
        raise HTTPException(404, "no prediction for this match")
    vals = value_rows(pred, price_board(m, mode, s))
    card = {
        "home": team_label(m.home_id),
        "away": team_label(m.away_id),
        "kickoff": m.kickoff.isoformat(),
        "stage": m.stage,
    }
    facts = analyst.fact_sheet(card, pred, vals)
    return {**analyst.explain(facts), "facts": facts}


class PlayerIn(BaseModel):
    name: str


@app.post("/api/players")
def create_player(body: PlayerIn, s: Session = Depends(db)):
    try:
        u = bets.create_user(s, body.name)
    except bets.BetError as e:
        raise HTTPException(400, str(e)) from e
    return {"name": u.name, "token": u.token, "bankroll": u.bankroll}


@app.get("/api/me")
def me(u: User = Depends(current_user), s: Session = Depends(db)):
    return bets.user_stats(s, s.merge(u))


class LegIn(BaseModel):
    match_id: int
    market: str
    selection: str
    line: float | None = None


class BetIn(BaseModel):
    legs: list[LegIn]
    stake: float
    mode: str


@app.post("/api/bets")
def post_bet(body: BetIn, u: User = Depends(current_user), s: Session = Depends(db)):
    u = s.merge(u)
    try:
        b = bets.place_bet(s, u, [lg.model_dump() for lg in body.legs], body.stake, body.mode)
    except bets.BetError as e:
        raise HTTPException(400, str(e)) from e
    return {"bet": bets.bet_json(b), "bankroll": u.bankroll}


@app.get("/api/bets")
def list_bets(u: User = Depends(current_user), s: Session = Depends(db)):
    rows = s.scalars(select(Bet).where(Bet.user_id == u.id).order_by(Bet.placed_at.desc()).limit(200)).all()
    return [bets.bet_json(b) for b in rows]


class KickoffIn(BaseModel):
    league: str = "MLS"
    day: str


@app.post("/api/replay/kickoff")
def kickoff(body: KickoffIn, u: User = Depends(current_user), s: Session = Depends(db)):
    return bets.replay_kickoff(s, s.merge(u), body.league, body.day)


@app.post("/api/settle")
def settle(s: Session = Depends(db)):
    return {"settled": bets.settle_live(s)}


@app.get("/api/leaderboard")
def board(mode: str = "live", s: Session = Depends(db)):
    return bets.leaderboard(s, mode)


@app.get("/api/ratings")
def ratings(s: Session = Depends(db)):
    return ratings_table(s)


@app.get("/api/backtest")
def backtest():
    path = settings.reports_dir / "backtest.json"
    if not path.exists():
        raise HTTPException(404, "run `oddsforge backtest` first")
    return json.loads(path.read_text())
