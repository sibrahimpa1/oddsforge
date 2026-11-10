"""Canonical team registry: one id per club, aliases for every data source, and the
venue facts that matter in MLS (travel distance, time zones, altitude, artificial turf).

Venue data is hand-curated from public stadium information. Surfaces change over time
(several clubs have moved between turf and grass), so `turf` is the current surface and is
treated as an approximation for older seasons.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class Team:
    id: str
    name: str
    short: str
    conference: str  # "East" / "West" (MLS); "" for other leagues
    lat: float
    lon: float
    altitude_m: int
    turf: bool
    utc_offset: int  # standard-time offset, enough for a time-zone-shift feature
    aliases: tuple[str, ...] = ()


MLS_TEAMS: list[Team] = [
    Team(
        "atl",
        "Atlanta United FC",
        "Atlanta",
        "East",
        33.755,
        -84.401,
        320,
        True,
        -5,
        ("Atlanta Utd", "Atlanta United"),
    ),
    Team("aus", "Austin FC", "Austin", "West", 30.388, -97.720, 200, False, -6),
    Team("clt", "Charlotte FC", "Charlotte", "East", 35.226, -80.853, 230, True, -5, ("Charlotte",)),
    Team("chi", "Chicago Fire FC", "Chicago", "East", 41.862, -87.617, 180, False, -6, ("Chicago Fire",)),
    Team("cin", "FC Cincinnati", "Cincinnati", "East", 39.111, -84.522, 150, False, -5),
    Team("col", "Colorado Rapids", "Colorado", "West", 39.806, -104.892, 1580, False, -7),
    Team("clb", "Columbus Crew", "Columbus", "East", 39.968, -83.017, 230, False, -5, ("Columbus Crew SC",)),
    Team("dc", "D.C. United", "D.C. United", "East", 38.868, -77.013, 10, False, -5, ("DC United",)),
    Team("dal", "FC Dallas", "Dallas", "West", 33.155, -96.835, 200, False, -6),
    Team("hou", "Houston Dynamo FC", "Houston", "West", 29.752, -95.352, 15, False, -6, ("Houston Dynamo",)),
    Team("mia", "Inter Miami CF", "Miami", "East", 26.193, -80.161, 3, False, -5, ("Inter Miami",)),
    Team("lag", "LA Galaxy", "LA Galaxy", "West", 33.864, -118.261, 20, False, -8, ("Los Angeles Galaxy",)),
    Team("lafc", "Los Angeles FC", "LAFC", "West", 34.013, -118.285, 60, False, -8),
    Team(
        "min",
        "Minnesota United FC",
        "Minnesota",
        "West",
        44.953,
        -93.165,
        260,
        False,
        -6,
        ("Minnesota United",),
    ),
    Team(
        "mtl",
        "CF Montréal",
        "Montréal",
        "East",
        45.563,
        -73.553,
        30,
        False,
        -5,
        ("CF Montreal", "Montreal Impact", "Club de Foot Montreal"),
    ),
    Team("nsh", "Nashville SC", "Nashville", "East", 36.130, -86.766, 160, False, -6),
    Team("ne", "New England Revolution", "New England", "East", 42.091, -71.264, 85, True, -5),
    Team("nyc", "New York City FC", "NYCFC", "East", 40.829, -73.926, 15, False, -5, ("New York City",)),
    Team(
        "nyrb",
        "New York Red Bulls",
        "NY Red Bulls",
        "East",
        40.737,
        -74.150,
        5,
        False,
        -5,
        ("Red Bull New York",),
    ),
    Team("orl", "Orlando City SC", "Orlando", "East", 28.541, -81.389, 30, False, -5, ("Orlando City",)),
    Team("phi", "Philadelphia Union", "Philadelphia", "East", 39.832, -75.378, 5, False, -5),
    Team(
        "por",
        "Portland Timbers",
        "Portland",
        "West",
        45.521,
        -122.692,
        60,
        True,
        -8,
        ("Portland Timbers FC",),
    ),
    Team("rsl", "Real Salt Lake", "Salt Lake", "West", 40.583, -111.893, 1340, False, -7),
    Team("sd", "San Diego FC", "San Diego", "West", 32.783, -117.120, 120, False, -8),
    Team("sj", "San Jose Earthquakes", "San Jose", "West", 37.351, -121.925, 20, False, -8),
    Team(
        "sea", "Seattle Sounders FC", "Seattle", "West", 47.595, -122.332, 5, True, -8, ("Seattle Sounders",)
    ),
    Team("skc", "Sporting Kansas City", "Sporting KC", "West", 39.122, -94.823, 280, False, -6),
    Team(
        "stl",
        "St. Louis City SC",
        "St. Louis",
        "West",
        38.631,
        -90.211,
        140,
        False,
        -6,
        ("St. Louis City", "St. Louis CITY SC"),
    ),
    Team("tor", "Toronto FC", "Toronto", "East", 43.633, -79.419, 80, False, -5),
    Team(
        "van",
        "Vancouver Whitecaps FC",
        "Vancouver",
        "West",
        49.277,
        -123.112,
        5,
        True,
        -8,
        ("Vancouver Whitecaps",),
    ),
    Team("chv", "Chivas USA", "Chivas USA", "West", 33.864, -118.261, 20, False, -8),
]

_BY_ID = {t.id: t for t in MLS_TEAMS}


def normalize(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


_ALIAS: dict[str, str] = {}
for _t in MLS_TEAMS:
    for _n in (_t.name, _t.short, *_t.aliases):
        _ALIAS[normalize(_n)] = _t.id


def mls_team_id(name: str) -> str | None:
    """Map any source's MLS team name to the canonical id (None if unknown)."""
    return _ALIAS.get(normalize(name))


def get_team(team_id: str) -> Team | None:
    return _BY_ID.get(team_id)


def slug(name: str) -> str:
    """Canonical id for clubs outside MLS (e.g. EPL), derived from the football-data name."""
    return normalize(name).replace(" ", "-")


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
