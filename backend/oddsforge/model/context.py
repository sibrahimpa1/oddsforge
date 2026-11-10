"""Match-context features that a team rating cannot see, all knowable before kickoff
(they come from the published schedule and venue facts, never from the result).

MLS-specific signal lives here: cross-country travel (Vancouver to Miami is ~4,500 km),
time-zone shifts, altitude in Colorado and Salt Lake, artificial turf, short rest and
congestion, and playoff knockout games.

Known gap, stated plainly: the free data covers league games only. Rest and congestion
therefore ignore CONCACAF Champions Cup, Leagues Cup and U.S. Open Cup fixtures. A production
version needs the full club calendar.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..teams import get_team, haversine_km

FEATURES = [
    "is_home",
    "rest_own",
    "rest_opp",
    "travel_km",
    "tz_shift",
    "venue_altitude",
    "altitude_unaccustomed",
    "venue_turf",
    "own_home_turf",
    "knockout",
    "season_progress",
    "games_last_10d_own",
    "games_last_10d_opp",
    "midweek",
    "cross_conference",
]


def _alt(m: float) -> float:
    """Kilometres above 1,000 m. Raw metres would give almost every stadium a unique value,
    and trees would use it as a hidden team identifier (double-counting team strength)."""
    return round(max(0.0, m - 1000.0) / 1000.0, 2)


def build_context(df: pd.DataFrame) -> pd.DataFrame:
    """df: one row per match with columns id, kickoff, home_id, away_id, knockout, season.
    Returns one row per match with home-side and away-side feature sets (prefix h_/a_)."""
    df = df.sort_values("kickoff").reset_index(drop=True)
    last_game: dict[str, pd.Timestamp] = {}
    recent: dict[str, list[pd.Timestamp]] = {}
    count_in_season: dict[tuple[str, str], int] = {}
    rows = []
    for r in df.itertuples(index=False):
        ko = pd.Timestamp(r.kickoff)
        feats = {"id": r.id}
        th, ta = get_team(r.home_id), get_team(r.away_id)
        travel = haversine_km(th.lat, th.lon, ta.lat, ta.lon) if th and ta else np.nan
        tz = abs(th.utc_offset - ta.utc_offset) if th and ta else np.nan
        cross = float(th.conference != ta.conference) if th and ta else np.nan
        local_hour_shift = th.utc_offset if th else -5
        weekday = (ko + pd.Timedelta(hours=local_hour_shift)).weekday()
        for side, team, opp in (("h", r.home_id, r.away_id), ("a", r.away_id, r.home_id)):
            t = get_team(team)
            rest_own = (ko - last_game[team]).total_seconds() / 86400 if team in last_game else 14.0
            rest_opp = (ko - last_game[opp]).total_seconds() / 86400 if opp in last_game else 14.0
            g10_own = sum(1 for k in recent.get(team, []) if (ko - k).days <= 10)
            g10_opp = sum(1 for k in recent.get(opp, []) if (ko - k).days <= 10)
            n_season = count_in_season.get((team, r.season), 0)
            feats.update(
                {
                    f"{side}_is_home": 1.0 if side == "h" else 0.0,
                    f"{side}_rest_own": min(rest_own, 14.0),
                    f"{side}_rest_opp": min(rest_opp, 14.0),
                    f"{side}_travel_km": 0.0 if side == "h" else travel,
                    f"{side}_tz_shift": 0.0 if side == "h" else tz,
                    f"{side}_venue_altitude": _alt(th.altitude_m) if th else np.nan,
                    f"{side}_altitude_unaccustomed": (
                        _alt(th.altitude_m) if th and t and _alt(t.altitude_m) == 0 else 0.0
                    ),
                    f"{side}_venue_turf": float(th.turf) if th else np.nan,
                    f"{side}_own_home_turf": float(t.turf) if t else np.nan,
                    f"{side}_knockout": float(bool(r.knockout)),
                    f"{side}_season_progress": min(n_season / 34.0, 1.2),
                    f"{side}_games_last_10d_own": g10_own,
                    f"{side}_games_last_10d_opp": g10_opp,
                    f"{side}_midweek": float(weekday in (1, 2, 3)),
                    f"{side}_cross_conference": cross,
                }
            )
        rows.append(feats)
        for team in (r.home_id, r.away_id):
            last_game[team] = ko
            recent.setdefault(team, []).append(ko)
            recent[team] = recent[team][-5:]
            count_in_season[(team, r.season)] = count_in_season.get((team, r.season), 0) + 1
    return pd.DataFrame(rows)


def side_matrix(ctx: pd.DataFrame, side: str) -> np.ndarray:
    return ctx[[f"{side}_{f}" for f in FEATURES]].to_numpy(dtype=float)
