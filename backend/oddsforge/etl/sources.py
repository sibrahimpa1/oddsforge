"""Download raw snapshots from the public sources. Raw files are written to data/raw and
committed, so the whole app (ETL, model, backtest, UI) runs offline without any API key.

Sources
- football-data.co.uk: MLS results + closing 1X2 odds (Pinnacle, best, average, Bet365, Betfair
  exchange) since 2012; EPL results + *opening and closing* 1X2, Asian handicap and O/U 2.5 odds.
- American Soccer Analysis (ASA) public API: MLS game-level xG, player xG/xA, goals added (g+),
  goalkeeper shot-stopping.
- ESPN public scoreboard: upcoming MLS fixtures, kickoff times, live/final scores, Bet365 1X2.
- The Odds API (optional, needs ODDS_API_KEY): multi-book 1X2, spreads and totals snapshots.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx

from ..config import settings

log = logging.getLogger(__name__)
UA = {"User-Agent": "oddsforge/0.1 (+https://github.com/sibrahimpa1/oddsforge)"}
ASA = "https://app.americansocceranalysis.com/api/v1/mls"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/scoreboard"
EPL_SEASONS = ["1516", "1617", "1718", "1819", "1920", "2021", "2122", "2223", "2324", "2425", "2526"]


def _client() -> httpx.Client:
    return httpx.Client(headers=UA, timeout=60, follow_redirects=True)


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def fetch_football_data(c: httpx.Client) -> None:
    out = settings.raw_dir / "football_data"
    r = c.get("https://www.football-data.co.uk/new/USA.csv")
    r.raise_for_status()
    _write(out / "USA.csv", r.content)
    for s in EPL_SEASONS:
        r = c.get(f"https://www.football-data.co.uk/mmz4281/{s}/E0.csv")
        if r.status_code == 200 and len(r.content) > 1000:
            _write(out / f"E0_{s}.csv", r.content)
    log.info("football-data: MLS + %d EPL seasons", len(EPL_SEASONS))


def fetch_asa(c: httpx.Client, player_seasons: list[str] | None = None) -> None:
    out = settings.raw_dir / "asa"
    for name, url in {
        "teams": f"{ASA}/teams",
        "games": f"{ASA}/games",
        "games_xgoals": f"{ASA}/games/xgoals",
        "players": f"{ASA}/players",
    }.items():
        r = c.get(url)
        r.raise_for_status()
        _write(out / f"{name}.json", r.content)
    this_year = datetime.now(UTC).year
    for season in player_seasons or [str(this_year - 1), str(this_year)]:
        for name, path in {
            "players_xgoals": "players/xgoals",
            "players_goals_added": "players/goals-added",
            "goalkeepers_xgoals": "goalkeepers/xgoals",
        }.items():
            r = c.get(f"{ASA}/{path}", params={"season_name": season})
            if r.status_code == 200:
                _write(out / f"{name}_{season}.json", r.content)
    log.info("ASA: games, xG and player seasons fetched")


def fetch_espn(c: httpx.Client, days_back: int = 21, days_ahead: int = 45) -> Path:
    """Fetch one scoreboard per day and merge into a single snapshot file."""
    today = date.today()
    events: dict[str, dict] = {}
    for i in range(-days_back, days_ahead + 1):
        d = today + timedelta(days=i)
        r = c.get(ESPN, params={"dates": d.strftime("%Y%m%d")})
        if r.status_code != 200:
            continue
        for e in r.json().get("events", []):
            events[e["id"]] = e
    snap = {"captured_at": datetime.now(UTC).isoformat(), "events": list(events.values())}
    path = settings.raw_dir / "espn" / "scoreboard.json"
    _write(path, json.dumps(snap).encode())
    log.info("ESPN: %d events", len(events))
    return path


def fetch_odds_api(c: httpx.Client) -> Path | None:
    if not settings.odds_api_key:
        return None
    r = c.get(
        "https://api.the-odds-api.com/v4/sports/soccer_usa_mls/odds",
        params={
            "apiKey": settings.odds_api_key,
            "regions": "us,eu",
            "markets": "h2h,spreads,totals",
            "oddsFormat": "decimal",
        },
    )
    r.raise_for_status()
    snap = {"captured_at": datetime.now(UTC).isoformat(), "events": r.json()}
    path = settings.raw_dir / "odds_api" / "mls_odds.json"
    _write(path, json.dumps(snap).encode())
    log.info(
        "The Odds API: %d events (requests left: %s)",
        len(snap["events"]),
        r.headers.get("x-requests-remaining"),
    )
    return path


def fetch_all(include_history: bool = True) -> None:
    with _client() as c:
        if include_history:
            fetch_football_data(c)
            fetch_asa(c)
        fetch_espn(c)
        try:
            fetch_odds_api(c)
        except httpx.HTTPError as exc:  # optional source, never block the pipeline
            log.warning("The Odds API failed: %s", exc)
