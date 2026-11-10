"""Load raw snapshots into the database (idempotent: safe to run on every schedule tick)."""

from __future__ import annotations

import csv
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import Match, OddsQuote, PlayerSeason, session
from ..teams import mls_team_id, slug

log = logging.getLogger(__name__)


def _f(v: str | None) -> float | None:
    try:
        x = float(v) if v not in (None, "") else None
    except ValueError:
        return None
    return x if x and x > 1.0 else None


def _num(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def _fd_datetime(d: str, t: str | None) -> datetime:
    fmt = "%d/%m/%Y" if len(d.split("/")[-1]) == 4 else "%d/%m/%y"
    day = datetime.strptime(d, fmt)
    if t:
        hh, mm = t.split(":")
        day = day.replace(hour=int(hh), minute=int(mm))
    return day


class MatchIndex:
    """Find an existing match by teams and kickoff within a tolerance (sources disagree on
    kickoff times by an hour or a time zone, never by more than a day and a half)."""

    def __init__(self, s: Session, league: str):
        self.by_pair: dict[tuple[str, str], list[Match]] = defaultdict(list)
        for m in s.scalars(select(Match).where(Match.league == league)):
            self.by_pair[(m.home_id, m.away_id)].append(m)

    def find(self, home: str, away: str, kickoff: datetime, tol_hours: float = 36) -> Match | None:
        best, best_dt = None, timedelta(hours=tol_hours)
        for m in self.by_pair.get((home, away), []):
            dt = abs(m.kickoff - kickoff)
            if dt <= best_dt:
                best, best_dt = m, dt
        return best

    def add(self, m: Match) -> None:
        self.by_pair[(m.home_id, m.away_id)].append(m)


def _set_odds(s: Session, m: Match, quotes: list[OddsQuote]) -> None:
    """Replace this match's quotes for the (market, book, timing) keys we are loading."""
    keys = {(q.market, q.book, q.timing) for q in quotes}
    for q in list(m.odds):
        if (q.market, q.book, q.timing) in keys:
            m.odds.remove(q)
    s.flush()
    m.odds.extend(quotes)


def load_mls_football_data(s: Session) -> int:
    path = settings.raw_dir / "football_data" / "USA.csv"
    idx = MatchIndex(s, "MLS")
    n = 0
    with path.open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            home, away = mls_team_id(r["Home"]), mls_team_id(r["Away"])
            if not home or not away or r.get("HG") in (None, ""):
                continue
            ko = _fd_datetime(r["Date"], r.get("Time"))
            m = idx.find(home, away, ko)
            if m is None:
                m = Match(league="MLS", season=r["Season"], kickoff=ko, home_id=home, away_id=away)
                s.add(m)
                idx.add(m)
            m.home_goals, m.away_goals, m.status = int(r["HG"]), int(r["AG"]), "final"
            quotes = []
            for book, pre in [
                ("pinnacle", "PSC"),
                ("best", "MaxC"),
                ("avg", "AvgC"),
                ("bet365", "B365C"),
                ("betfair_ex", "BFEC"),
            ]:
                h, d, a = _f(r.get(pre + "H")), _f(r.get(pre + "D")), _f(r.get(pre + "A"))
                if h and d and a:
                    quotes.append(
                        OddsQuote(market="1x2", book=book, timing="close", price_a=h, price_b=d, price_c=a)
                    )
            _set_odds(s, m, quotes)
            n += 1
    return n


def load_epl_football_data(s: Session) -> int:
    n = 0
    idx = MatchIndex(s, "EPL")
    for path in sorted((settings.raw_dir / "football_data").glob("E0_*.csv")):
        code = path.stem.split("_")[1]
        season = f"20{code[:2]}-{code[2:]}"
        with path.open(encoding="utf-8-sig", errors="replace") as fh:
            for r in csv.DictReader(fh):
                if not r.get("HomeTeam") or r.get("FTHG") in (None, ""):
                    continue
                home, away = slug(r["HomeTeam"]), slug(r["AwayTeam"])
                ko = _fd_datetime(r["Date"], r.get("Time"))
                m = idx.find(home, away, ko)
                if m is None:
                    m = Match(league="EPL", season=season, kickoff=ko, home_id=home, away_id=away)
                    s.add(m)
                    idx.add(m)
                m.home_goals, m.away_goals, m.status = int(r["FTHG"]), int(r["FTAG"]), "final"
                q: list[OddsQuote] = []
                for timing, sfx in [("open", ""), ("close", "C")]:
                    for book, pre in [
                        ("pinnacle", "PS"),
                        ("best", "Max"),
                        ("avg", "Avg"),
                        ("bet365", "B365"),
                    ]:
                        h, d, a = (_f(r.get(f"{pre}{sfx}{x}")) for x in "HDA")
                        if h and d and a:
                            q.append(
                                OddsQuote(
                                    market="1x2", book=book, timing=timing, price_a=h, price_b=d, price_c=a
                                )
                            )
                    for book, pre in [("pinnacle", "P"), ("best", "Max"), ("avg", "Avg")]:
                        o, u = _f(r.get(f"{pre}{sfx}>2.5")), _f(r.get(f"{pre}{sfx}<2.5"))
                        if o and u:
                            q.append(
                                OddsQuote(
                                    market="ou", line=2.5, book=book, timing=timing, price_a=o, price_b=u
                                )
                            )
                    line = _num(r.get("AHh" if sfx == "" else "AHCh"))
                    for book, pre in [("pinnacle", "P"), ("best", "Max"), ("avg", "Avg")]:
                        h, a = _f(r.get(f"{pre}{sfx}AHH")), _f(r.get(f"{pre}{sfx}AHA"))
                        if line is not None and h and a:
                            q.append(
                                OddsQuote(
                                    market="ah", line=line, book=book, timing=timing, price_a=h, price_b=a
                                )
                            )
                _set_odds(s, m, q)
                n += 1
    return n


def _asa_team_map(raw: Path) -> dict[str, str]:
    teams = json.loads((raw / "teams.json").read_text())
    return {t["team_id"]: mls_team_id(t["team_name"]) or slug(t["team_name"]) for t in teams}


def load_asa(s: Session) -> int:
    raw = settings.raw_dir / "asa"
    tmap = _asa_team_map(raw)
    games = {g["game_id"]: g for g in json.loads((raw / "games.json").read_text())}
    xg = {g["game_id"]: g for g in json.loads((raw / "games_xgoals.json").read_text())}
    idx = MatchIndex(s, "MLS")
    n = 0
    for gid, g in games.items():
        home, away = tmap.get(g["home_team_id"]), tmap.get(g["away_team_id"])
        if not home or not away:
            continue
        ko = datetime.strptime(g["date_time_utc"].replace(" UTC", ""), "%Y-%m-%d %H:%M:%S")
        m = idx.find(home, away, ko)
        if m is None:
            m = Match(
                league="MLS", season=g["season_name"], kickoff=ko, home_id=home, away_id=away, status="final"
            )
            m.home_goals, m.away_goals = g["home_score"], g["away_score"]
            s.add(m)
            idx.add(m)
        m.kickoff = ko  # ASA kickoff is true UTC; football-data times are UK local
        m.asa_id = gid
        m.knockout = bool(g.get("knockout_game"))
        x = xg.get(gid)
        if x:
            m.home_xg, m.away_xg = x.get("home_team_xgoals"), x.get("away_team_xgoals")
        n += 1
    return n


def load_players(s: Session) -> int:
    raw = settings.raw_dir / "asa"
    tmap = _asa_team_map(raw)
    names = {p["player_id"]: p["player_name"] for p in json.loads((raw / "players.json").read_text())}
    n = 0
    for xf in sorted(raw.glob("players_xgoals_*.json")):
        season = xf.stem.rsplit("_", 1)[1]
        s.execute(delete(PlayerSeason).where(PlayerSeason.season == season))
        ga = {}
        gaf = raw / f"players_goals_added_{season}.json"
        if gaf.exists():
            for p in json.loads(gaf.read_text()):
                tot = sum(a["goals_added_above_avg"] for a in p["data"])
                dfn = sum(
                    a["goals_added_above_avg"]
                    for a in p["data"]
                    if a["action_type"] in ("Interrupting", "Fouling")
                )
                ga[(p["player_id"], _first(p["team_id"]))] = (tot, dfn)
        gk = {}
        gkf = raw / f"goalkeepers_xgoals_{season}.json"
        if gkf.exists():
            for p in json.loads(gkf.read_text()):
                gk[(p["player_id"], _first(p["team_id"]))] = (p["shots_faced"], p["goals_minus_xgoals_gk"])
        for p in json.loads(xf.read_text()):
            team_raw = _first(p["team_id"])
            team = tmap.get(team_raw)
            if not team:
                continue
            key = (p["player_id"], team_raw)
            pos = p.get("general_position") or ("GK" if key in gk else "?")
            tot, dfn = ga.get(key, (0.0, 0.0))
            shots, gmx = gk.get(key, (0, 0.0))
            s.add(
                PlayerSeason(
                    player_id=p["player_id"],
                    name=names.get(p["player_id"], p["player_id"]),
                    team_id=team,
                    season=season,
                    position=pos,
                    minutes=int(p["minutes_played"]),
                    xg=p.get("xgoals", 0.0) or 0.0,
                    xa=p.get("xassists", 0.0) or 0.0,
                    goals=p.get("goals", 0) or 0,
                    gplus=tot,
                    gplus_def=dfn,
                    gk_shots_faced=shots,
                    gk_goals_minus_xg=gmx,
                )
            )
            n += 1
        # goalkeepers who never appear in the outfield xG table
        seen = {(p["player_id"], _first(p["team_id"])) for p in json.loads(xf.read_text())}
        for (pid, team_raw), (shots, gmx) in gk.items():
            if (pid, team_raw) in seen or not tmap.get(team_raw):
                continue
            mins = next(
                (g["minutes_played"] for g in json.loads(gkf.read_text()) if g["player_id"] == pid), 0
            )
            s.add(
                PlayerSeason(
                    player_id=pid,
                    name=names.get(pid, pid),
                    team_id=tmap[team_raw],
                    season=season,
                    position="GK",
                    minutes=int(mins),
                    gk_shots_faced=shots,
                    gk_goals_minus_xg=gmx,
                )
            )
            n += 1
    return n


def _first(team_id):
    return team_id[0] if isinstance(team_id, list) else team_id


def load_espn(s: Session) -> int:
    path = settings.raw_dir / "espn" / "scoreboard.json"
    if not path.exists():
        return 0
    snap = json.loads(path.read_text())
    captured = datetime.fromisoformat(snap["captured_at"]).replace(tzinfo=None)
    idx = MatchIndex(s, "MLS")
    n = 0
    for e in snap["events"]:
        c = e["competitions"][0]
        side = {x["homeAway"]: x for x in c["competitors"]}
        home, away = (
            mls_team_id(side["home"]["team"]["displayName"]),
            mls_team_id(side["away"]["team"]["displayName"]),
        )
        if not home or not away:
            continue
        ko = datetime.strptime(e["date"], "%Y-%m-%dT%H:%MZ")
        m = idx.find(home, away, ko)
        if m is None:
            m = Match(
                league="MLS", season=str(ko.year), kickoff=ko, home_id=home, away_id=away, status="scheduled"
            )
            s.add(m)
            idx.add(m)
        m.espn_id = e["id"]
        state = e["status"]["type"]["state"]  # pre | in | post
        stage = (e.get("season") or {}).get("slug", "") or c.get("type", {}).get("abbreviation", "")
        m.stage = stage
        m.knockout = m.knockout or "playoff" in stage.lower() or "round" in stage.lower()
        venue = (c.get("venue") or {}).get("fullName", "")
        m.venue = "" if venue.lower() in ("no stadium", "tbd") else venue
        if state == "post" and e["status"]["type"].get("completed"):
            m.home_goals, m.away_goals = int(side["home"]["score"]), int(side["away"]["score"])
            m.status = "final"
        elif state == "in":
            m.status = "live"
        elif m.status != "final":
            m.status = "scheduled"
            m.kickoff = ko
        o = (c.get("odds") or [None])[0]
        if o and o.get("homeTeamOdds", {}).get("value") and m.status == "scheduled":
            h, d, a = (
                o["homeTeamOdds"]["value"],
                (o.get("drawOdds") or {}).get("value"),
                o["awayTeamOdds"]["value"],
            )
            if h and d and a and min(h, d, a) > 1:
                _set_odds(
                    s,
                    m,
                    [
                        OddsQuote(
                            market="1x2",
                            book="bet365",
                            timing="snapshot",
                            captured_at=captured,
                            price_a=h,
                            price_b=d,
                            price_c=a,
                        )
                    ],
                )
        n += 1
    return n


def load_odds_api(s: Session) -> int:
    path = settings.raw_dir / "odds_api" / "mls_odds.json"
    if not path.exists():
        return 0
    snap = json.loads(path.read_text())
    captured = datetime.fromisoformat(snap["captured_at"]).replace(tzinfo=None)
    idx = MatchIndex(s, "MLS")
    n = 0
    for e in snap["events"]:
        home, away = mls_team_id(e["home_team"]), mls_team_id(e["away_team"])
        if not home or not away:
            continue
        ko = datetime.strptime(e["commence_time"], "%Y-%m-%dT%H:%M:%SZ")
        m = idx.find(home, away, ko)
        if m is None:
            continue
        quotes = []
        for bk in e.get("bookmakers", []):
            book = bk["key"]
            for mk in bk.get("markets", []):
                oc = {o["name"]: o for o in mk["outcomes"]}
                if mk["key"] == "h2h" and {e["home_team"], e["away_team"], "Draw"} <= oc.keys():
                    quotes.append(
                        OddsQuote(
                            market="1x2",
                            book=book,
                            timing="snapshot",
                            captured_at=captured,
                            price_a=oc[e["home_team"]]["price"],
                            price_b=oc["Draw"]["price"],
                            price_c=oc[e["away_team"]]["price"],
                        )
                    )
                elif mk["key"] == "spreads" and e["home_team"] in oc and e["away_team"] in oc:
                    quotes.append(
                        OddsQuote(
                            market="ah",
                            line=oc[e["home_team"]]["point"],
                            book=book,
                            timing="snapshot",
                            captured_at=captured,
                            price_a=oc[e["home_team"]]["price"],
                            price_b=oc[e["away_team"]]["price"],
                        )
                    )
                elif mk["key"] == "totals" and "Over" in oc and "Under" in oc:
                    quotes.append(
                        OddsQuote(
                            market="ou",
                            line=oc["Over"]["point"],
                            book=book,
                            timing="snapshot",
                            captured_at=captured,
                            price_a=oc["Over"]["price"],
                            price_b=oc["Under"]["price"],
                        )
                    )
        _set_odds(s, m, quotes)
        n += 1
    return n


def load_all() -> dict[str, int]:
    out = {}
    with session() as s:
        out["mls_football_data"] = load_mls_football_data(s)
        s.flush()
        out["mls_asa"] = load_asa(s)
        s.flush()
        out["players"] = load_players(s)
        out["epl_football_data"] = load_epl_football_data(s)
        s.flush()
        out["espn"] = load_espn(s)
        s.flush()
        out["odds_api"] = load_odds_api(s)
        s.commit()
    log.info("ETL loaded: %s", out)
    return out
