"""Paper betting with fake money: accounts, bet slip validation, settlement, P&L, leaderboards.

Guard rails are deliberate (and listed on the Responsible play page):
- prices come from the server, never from the client;
- one bet risks at most 5% of the bankroll (and at most 100 credits);
- a daily loss limit stops play for the day;
- accumulators: at most 6 legs, one leg per match (correlated legs are not allowed);
- replay bets are only accepted on matchdays the player has not revealed yet, and replay
  results never count towards the live leaderboard.
"""

from __future__ import annotations

import math
import secrets
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import KV, Bet, BetLeg, Match, User, utcnow
from ..markets.settlement import settle_leg
from ..service import local_day, lookup_price, prediction, value_rows


class BetError(ValueError):
    pass


def create_user(s: Session, name: str) -> User:
    name = name.strip()[:32]
    if len(name) < 2:
        raise BetError("name must be at least 2 characters")
    if s.scalar(select(User).where(func.lower(User.name) == name.lower())):
        raise BetError("that name is taken")
    u = User(name=name, token=secrets.token_urlsafe(24), bankroll=settings.starting_bankroll)
    s.add(u)
    s.commit()
    return u


def user_by_token(s: Session, token: str | None) -> User | None:
    if not token:
        return None
    return s.scalar(select(User).where(User.token == token))


def revealed_days(s: Session, user: User) -> set[str]:
    kv = s.get(KV, f"revealed:{user.id}")
    return set(kv.value.get("days", [])) if kv else set()


def _mark_revealed(s: Session, user: User, key: str) -> None:
    kv = s.get(KV, f"revealed:{user.id}")
    if kv is None:
        s.add(KV(key=f"revealed:{user.id}", value={"days": [key]}))
    else:
        kv.value = {"days": sorted(set(kv.value.get("days", [])) | {key})}


def day_key(m: Match) -> str:
    return f"{m.league}:{local_day(m)}"


def losses_today(s: Session, user: User) -> float:
    since = utcnow() - timedelta(hours=24)
    bets = s.scalars(select(Bet).where(Bet.user_id == user.id, Bet.placed_at >= since)).all()
    staked = sum(b.stake for b in bets)
    returned = sum(b.payout for b in bets if b.status != "open")
    return max(0.0, staked - returned)


def stake_limit(user: User) -> float:
    return round(min(settings.max_stake_abs, user.bankroll * settings.max_stake_fraction), 2)


def place_bet(s: Session, user: User, legs: list[dict], stake: float, mode: str) -> Bet:
    if mode not in ("live", "replay"):
        raise BetError("mode must be live or replay")
    if not legs:
        raise BetError("the slip is empty")
    if len(legs) > settings.max_acca_legs:
        raise BetError(f"at most {settings.max_acca_legs} legs in an accumulator")
    if len({lg["match_id"] for lg in legs}) != len(legs):
        raise BetError("one leg per match: same-match legs are correlated and not allowed")
    if not (stake > 0 and math.isfinite(stake)):
        raise BetError("stake must be positive")
    limit = stake_limit(user)
    if stake > limit + 1e-9:
        raise BetError(f"stake limit is {limit:.2f} (5% of bankroll, max {settings.max_stake_abs:.0f})")
    if losses_today(s, user) + stake > settings.daily_loss_limit:
        raise BetError(
            f"daily loss limit of {settings.daily_loss_limit:.0f} credits reached. Take a break, it resets in 24h"
        )

    revealed = revealed_days(s, user) if mode == "replay" else set()
    bet = Bet(
        user_id=user.id,
        kind="single" if len(legs) == 1 else "acca",
        mode=mode,
        stake=round(stake, 2),
        odds=1.0,
    )
    evs = []
    for lg in legs:
        m = s.get(Match, int(lg["match_id"]))
        if m is None:
            raise BetError("unknown match")
        if mode == "live" and (m.status != "scheduled" or m.kickoff <= utcnow()):
            raise BetError(f"{m.home_id} v {m.away_id} has started; live betting is pregame only")
        if mode == "replay":
            if m.status != "final":
                raise BetError("replay mode is for historical matches")
            if day_key(m) in revealed:
                raise BetError("you already revealed this matchday")
        line = lg.get("line")
        q = lookup_price(s, m, mode, lg["market"], lg["selection"], line)
        if q is None:
            raise BetError(f"no price available for {lg['market']} {lg['selection']}")
        pred = prediction(s, m, mode)
        prob = None
        if pred:
            for row in value_rows(pred, {lg["market"]: [q]}):
                prob, evs = row["model_prob"], evs + [row["ev"]]
        bet.legs.append(
            BetLeg(
                match_id=m.id,
                market=lg["market"],
                selection=lg["selection"],
                line=q["line"],
                odds=q["price"],
                model_prob=prob,
            )
        )
        bet.odds *= q["price"]
    bet.odds = round(bet.odds, 3)
    if len(evs) == len(legs):
        bet.model_ev = math.prod(1 + e for e in evs) - 1
    user.bankroll = round(user.bankroll - bet.stake, 2)
    s.add(bet)
    s.commit()
    return bet


def _settle_bet_if_done(bet: Bet, user: User) -> None:
    if bet.status != "open" or any(lg.result is None for lg in bet.legs):
        return
    factor = math.prod(lg.factor for lg in bet.legs)
    bet.payout = round(bet.stake * factor, 2)
    if len(bet.legs) == 1:
        bet.status = bet.legs[0].result
    else:
        bet.status = "won" if factor > 1 else ("void" if math.isclose(factor, 1) else "lost")
    bet.settled_at = utcnow()
    user.bankroll = round(user.bankroll + bet.payout, 2)


def _settle_leg(lg: BetLeg) -> None:
    m = lg.match
    if lg.result is None and m.is_final:
        out = settle_leg(lg.market, lg.selection, lg.line, lg.odds, m.home_goals, m.away_goals)
        lg.result, lg.factor = out.result, out.factor


def settle_live(s: Session) -> int:
    """Settle live bets whose matches are final. Run after every ETL refresh."""
    n = 0
    for bet in s.scalars(select(Bet).where(Bet.status == "open", Bet.mode == "live")).all():
        for lg in bet.legs:
            _settle_leg(lg)
        before = bet.status
        _settle_bet_if_done(bet, bet.user)
        n += before != bet.status
    s.commit()
    return n


def replay_kickoff(s: Session, user: User, league: str, day: str) -> dict:
    """Reveal one historical matchday for this player and settle their replay bets on it."""
    key = f"{league}:{day}"
    _mark_revealed(s, user, key)
    s.flush()
    revealed = revealed_days(s, user) | {key}
    settled = []
    for bet in s.scalars(
        select(Bet).where(Bet.user_id == user.id, Bet.mode == "replay", Bet.status == "open")
    ).all():
        if all(day_key(lg.match) in revealed for lg in bet.legs):
            for lg in bet.legs:
                _settle_leg(lg)
            _settle_bet_if_done(bet, user)
            settled.append(bet.id)
    s.commit()
    return {"revealed": key, "settled_bets": settled, "bankroll": user.bankroll}


def bet_json(b: Bet) -> dict:
    return {
        "id": b.id,
        "kind": b.kind,
        "mode": b.mode,
        "stake": b.stake,
        "odds": b.odds,
        "status": b.status,
        "payout": b.payout,
        "profit": round(b.payout - b.stake, 2) if b.status != "open" else None,
        "model_ev": b.model_ev,
        "placed_at": b.placed_at.isoformat(),
        "settled_at": b.settled_at.isoformat() if b.settled_at else None,
        "legs": [
            {
                "match_id": lg.match_id,
                "home": lg.match.home_id,
                "away": lg.match.away_id,
                "league": lg.match.league,
                "kickoff": lg.match.kickoff.isoformat(),
                "market": lg.market,
                "selection": lg.selection,
                "line": lg.line,
                "odds": lg.odds,
                "model_prob": lg.model_prob,
                "result": lg.result,
                "score": f"{lg.match.home_goals}-{lg.match.away_goals}" if lg.result else None,
            }
            for lg in b.legs
        ],
    }


def user_stats(s: Session, user: User) -> dict:
    bets = s.scalars(select(Bet).where(Bet.user_id == user.id).order_by(Bet.placed_at)).all()
    out = {
        "name": user.name,
        "bankroll": user.bankroll,
        "starting_bankroll": settings.starting_bankroll,
        "stake_limit": stake_limit(user),
        "daily_loss_limit": settings.daily_loss_limit,
        "lost_last_24h": round(losses_today(s, user), 2),
    }
    for mode in ("live", "replay"):
        mb = [b for b in bets if b.mode == mode]
        settled = [b for b in mb if b.status != "open"]
        staked = sum(b.stake for b in settled)
        profit = sum(b.payout - b.stake for b in settled)
        evs = [b.model_ev for b in mb if b.model_ev is not None]
        out[mode] = {
            "bets": len(mb),
            "open": len(mb) - len(settled),
            "settled": len(settled),
            "staked": round(staked, 2),
            "profit": round(profit, 2),
            "roi": profit / staked if staked else None,
            "won": sum(1 for b in settled if b.payout > b.stake),
            "avg_model_ev": sum(evs) / len(evs) if evs else None,
        }
    cum, curve = 0.0, []
    for b in sorted([b for b in bets if b.settled_at], key=lambda b: b.settled_at):
        cum += b.payout - b.stake
        curve.append({"t": b.settled_at.isoformat(), "pnl": round(cum, 2), "mode": b.mode})
    out["pnl_curve"] = curve
    return out


def leaderboard(s: Session, mode: str = "live", min_bets: int = 1) -> list[dict]:
    rows = []
    for u in s.scalars(select(User)).all():
        settled = [b for b in u.bets if b.mode == mode and b.status != "open"]
        if len(settled) < min_bets:
            continue
        staked = sum(b.stake for b in settled)
        profit = sum(b.payout - b.stake for b in settled)
        rows.append(
            {
                "name": u.name,
                "bets": len(settled),
                "staked": round(staked, 2),
                "profit": round(profit, 2),
                "roi": profit / staked if staked else 0.0,
                "bankroll": u.bankroll,
            }
        )
    return sorted(rows, key=lambda r: -r["profit"])


def is_open_for_betting(m: Match, now: datetime | None = None) -> bool:
    return m.status == "scheduled" and m.kickoff > (now or utcnow())
