"""Player availability: what a missing player is worth in expected goals.

"injured_players = 1" treats Lionel Messi and a backup full-back the same. This module values a
player against the specific player who replaces him, in goal units, and turns absences into
multipliers on the two expected-goal rates that feed the score matrix.

Method (season-to-date data from American Soccer Analysis):
- Attack: chance production per 90 = (xG + xA) / minutes * 90. A goal usually has a shooter AND
  a passer, so the player's loss is scaled by his share of the team's xG+xA, not added raw.
- Replacement: the next player at the same position on the same roster (real bench quality),
  falling back to a league replacement level (25th percentile of regulars at that position).
- Availability already priced in: a player who normally plays 60% of minutes is already
  missing 40% of the time in the team rating, so only `minutes_share` of his edge is removed.
- Defence: goals added (g+) from Interrupting + Fouling, per 90, above the replacement.
- Goalkeepers: goals prevented per shot (xG faced minus goals), shrunk heavily towards zero
  because shot-stopping samples are tiny, times the shots this team usually faces.
- Every adjustment is capped. Season aggregates cannot see role changes, form or chemistry;
  this is a prior, not an oracle. (In the backtest it is OFF: free data has no timestamped
  historical lineups, and using today's player stats on old games would leak.)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sqlalchemy import select

from ..db import PlayerSeason, session

ATTACK_POS = {"ST", "W", "AM", "CM"}
DEF_POS = {"CB", "FB", "DM", "CM"}
POS_GROUP = {"ST": "ST", "W": "W", "AM": "AM", "CM": "CM", "DM": "DM", "CB": "CB", "FB": "FB", "GK": "GK"}
GK_SHRINK_SHOTS = 250.0
MAX_ATTACK_LOSS = 0.25  # at most -25% on a team's expected goals from absences
MAX_DEF_LOSS = 0.45  # at most +0.45 goals conceded from absences


@dataclass
class PlayerValue:
    player_id: str
    name: str
    position: str
    minutes: int
    minutes_share: float
    attack_p90: float
    replacement: str
    attack_loss: float  # fraction of own expected goals lost if absent
    defence_loss: float  # goals per match added to the opponent if absent
    gk_loss: float  # goals per match added to the opponent if absent (goalkeepers)

    @property
    def impact_score(self) -> float:
        return self.attack_loss * 1.4 + self.defence_loss + self.gk_loss


def _latest_season(team_id: str) -> list[PlayerSeason]:
    with session() as s:
        seasons = sorted(
            {r for (r,) in s.execute(select(PlayerSeason.season).where(PlayerSeason.team_id == team_id))},
            reverse=True,
        )
        for season in seasons:
            rows = list(
                s.scalars(
                    select(PlayerSeason).where(PlayerSeason.team_id == team_id, PlayerSeason.season == season)
                )
            )
            if sum(r.minutes for r in rows) > 90 * 11 * 8:  # at least ~8 games played
                return rows
    return []


def _league_replacement(season: str) -> dict[str, tuple[float, float]]:
    with session() as s:
        rows = list(
            s.scalars(select(PlayerSeason).where(PlayerSeason.season == season, PlayerSeason.minutes >= 600))
        )
    out = {}
    for pos in POS_GROUP:
        g = [r for r in rows if r.position == pos]
        if not g:
            out[pos] = (0.0, 0.0)
            continue
        att = np.percentile([(r.xg + r.xa) / r.minutes * 90 for r in g], 25)
        dfn = np.percentile([r.gplus_def / r.minutes * 90 for r in g], 25)
        out[pos] = (float(att), float(dfn))
    return out


def team_player_values(team_id: str) -> list[PlayerValue]:
    rows = _latest_season(team_id)
    if not rows:
        return []
    season = rows[0].season
    repl = _league_replacement(season)
    team_minutes = sum(r.minutes for r in rows)
    games = max(team_minutes / (90 * 11), 1.0)
    team_att = sum(r.xg + r.xa for r in rows) / games  # xG + xA per game
    gks = sorted([r for r in rows if r.position == "GK"], key=lambda r: -r.minutes)
    shots_per_game = (sum(r.gk_shots_faced for r in gks) / games) if gks else 12.0
    out = []
    for r in rows:
        if r.minutes < 90:
            continue
        share = min(r.minutes / (games * 90), 1.0)
        att90 = (r.xg + r.xa) / r.minutes * 90
        def90 = r.gplus_def / r.minutes * 90
        # bench: same position, fewer minutes, at least 180 minutes of evidence
        bench = [
            b
            for b in rows
            if b.position == r.position
            and b.player_id != r.player_id
            and b.minutes < r.minutes
            and b.minutes >= 180
        ]
        if bench:
            b = max(bench, key=lambda x: x.minutes)
            r_att, r_def, r_name = (b.xg + b.xa) / b.minutes * 90, b.gplus_def / b.minutes * 90, b.name
            # a thin bench sample is regressed towards league replacement level
            w = b.minutes / (b.minutes + 900)
            la, ld = repl.get(r.position, (0.0, 0.0))
            r_att, r_def = w * r_att + (1 - w) * la, w * r_def + (1 - w) * ld
        else:
            r_att, r_def = repl.get(r.position, (0.0, 0.0))
            r_name = "replacement level"
        attack_loss = max(0.0, att90 - r_att) * share / max(team_att, 0.5) if r.position != "GK" else 0.0
        defence_loss = max(0.0, def90 - r_def) * share if r.position in DEF_POS else 0.0
        gk_loss = 0.0
        if r.position == "GK":
            prevented = -r.gk_goals_minus_xg / (r.gk_shots_faced + GK_SHRINK_SHOTS)
            backup = next((g for g in gks if g.player_id != r.player_id), None)
            b_prev = -backup.gk_goals_minus_xg / (backup.gk_shots_faced + GK_SHRINK_SHOTS) if backup else 0.0
            r_name = backup.name if backup else "replacement level"
            gk_loss = max(0.0, prevented - b_prev) * shots_per_game * share
        out.append(
            PlayerValue(
                r.player_id,
                r.name,
                r.position,
                r.minutes,
                share,
                att90,
                r_name,
                attack_loss,
                defence_loss,
                gk_loss,
            )
        )
    return sorted(out, key=lambda p: -p.impact_score)


def apply_absences(
    lh: float, la: float, home_out: list[PlayerValue], away_out: list[PlayerValue]
) -> tuple[float, float, dict]:
    ha = min(sum(p.attack_loss for p in home_out), MAX_ATTACK_LOSS)
    aa = min(sum(p.attack_loss for p in away_out), MAX_ATTACK_LOSS)
    hd = min(sum(p.defence_loss + p.gk_loss for p in home_out), MAX_DEF_LOSS)
    ad = min(sum(p.defence_loss + p.gk_loss for p in away_out), MAX_DEF_LOSS)
    new_lh = lh * (1 - ha) + ad
    new_la = la * (1 - aa) + hd
    return (
        new_lh,
        new_la,
        {
            "home_attack_loss": ha,
            "away_attack_loss": aa,
            "home_defence_loss": hd,
            "away_defence_loss": ad,
            "delta_lh": new_lh - lh,
            "delta_la": new_la - la,
        },
    )
