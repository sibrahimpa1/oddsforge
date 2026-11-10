"""AI match analyst: explains *why* the model prices a match the way it does.

The model never decides anything here; Claude only turns the numbers (ratings, expected goals,
context contributions, absences, market comparison) into a short, plain-English read, and is
told to say "pass" when the edge is small. Without ANTHROPIC_API_KEY a deterministic
template produces the same facts, so the app works offline.
"""

from __future__ import annotations

import json
import logging

from .config import settings

log = logging.getLogger(__name__)

SYSTEM = """You are a soccer betting analyst writing for a fake-money prediction game.
You get a JSON fact sheet produced by a quantitative model. Explain the model's view in 120-170 words:
1) what drives the expected goals (team strength from xG-weighted ratings, venue and context factors, absences),
2) where the model disagrees with the market and by how much,
3) a clear verdict: "value", "small edge" or "pass".
Rules: use only numbers from the fact sheet; never invent injuries, news or players; say plainly that
markets are efficient and most edges under 3% are noise; no hype, no guarantees, no encouragement to gamble.
Plain text, no markdown headings."""

FEATURE_LABELS = {
    "rest_own": "rest days",
    "rest_opp": "opponent rest",
    "travel_km": "travel distance",
    "tz_shift": "time-zone shift",
    "venue_altitude": "altitude",
    "altitude_unaccustomed": "altitude for a sea-level team",
    "venue_turf": "artificial turf",
    "own_home_turf": "turf familiarity",
    "knockout": "playoff knockout",
    "season_progress": "season phase",
    "games_last_10d_own": "congestion",
    "games_last_10d_opp": "opponent congestion",
    "midweek": "midweek game",
    "cross_conference": "cross-conference trip",
    "is_home": "home advantage",
}


def fact_sheet(match: dict, pred: dict, values: list[dict]) -> dict:
    lad = pred["ladder"]
    ctx = []
    for f, c in (pred.get("context") or {}).items():
        for side in ("home", "away"):
            if abs(c[side]) >= 0.01:
                ctx.append(
                    {
                        "team": side,
                        "factor": FEATURE_LABELS.get(f, f),
                        "effect_pct": round((2.718281828 ** c[side] - 1) * 100, 1),
                        "value": round(c[f"value_{side}"], 1),
                    }
                )
    ctx.sort(key=lambda x: -abs(x["effect_pct"]))
    return {
        "match": f"{match['home']['name']} vs {match['away']['name']}",
        "kickoff_utc": match["kickoff"],
        "stage": match.get("stage") or "regular season",
        "expected_goals": {
            "home": round(lad["xg_home"], 2),
            "away": round(lad["xg_away"], 2),
            "from_team_strength_only": {
                "home": round(pred["base_lam_h"], 2),
                "away": round(pred["base_lam_a"], 2),
            },
        },
        "model_1x2": {k: round(v, 3) for k, v in lad["1x2"].items()},
        "model_btts_yes": round(lad["btts"]["yes"], 3),
        "most_likely_scores": lad["top_scores"][:3],
        "context_effects_on_expected_goals": ctx[:6],
        "absences": pred.get("lineup"),
        "market_comparison": [
            {
                k: (round(v, 3) if isinstance(v, float) else v)
                for k, v in r.items()
                if k
                in (
                    "market",
                    "selection",
                    "line",
                    "price",
                    "book",
                    "model_prob",
                    "market_prob",
                    "ev",
                    "verdict",
                )
            }
            for r in values[:6]
        ],
    }


def offline_explanation(facts: dict) -> str:
    xg = facts["expected_goals"]
    p = facts["model_1x2"]
    parts = [
        f"The model expects {xg['home']} goals for the home side and {xg['away']} for the visitors "
        f"(team strength alone: {xg['from_team_strength_only']['home']} v {xg['from_team_strength_only']['away']})."
    ]
    if facts["context_effects_on_expected_goals"]:
        top = facts["context_effects_on_expected_goals"][:3]
        parts.append(
            "Context adjustments: "
            + "; ".join(
                f"{c['factor']} {'+' if c['effect_pct'] > 0 else ''}{c['effect_pct']}% for the {c['team']} side"
                for c in top
            )
            + "."
        )
    if facts.get("absences") and facts["absences"].get("absent"):
        a = facts["absences"]
        parts.append(
            f"Absences ({', '.join(a['absent'])}) move expected goals by {a['delta_lh']:+.2f} (home) and {a['delta_la']:+.2f} (away)."
        )
    parts.append(f"That gives home {p['home']:.0%}, draw {p['draw']:.0%}, away {p['away']:.0%}.")
    vals = [v for v in facts["market_comparison"] if v.get("verdict") == "value"]
    if vals:
        v = vals[0]
        line = f" {v['line']:+g}" if v.get("line") is not None else ""
        parts.append(
            f"Best edge: {v['market'].upper()} {v['selection']}{line} at {v['price']} ({v['book']}), "
            f"model {v['model_prob']:.1%} vs market {v['market_prob']:.1%}, EV {v['ev']:+.1%}. "
            "Verdict: small edge. Closing prices are efficient, so treat it as an opinion, not a certainty."
        )
    else:
        parts.append("No selection clears the 3% edge threshold against the market. Verdict: pass.")
    return " ".join(parts)


def explain(facts: dict) -> dict:
    if settings.anthropic_api_key and not settings.offline:
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            resp = client.beta.messages.create(
                model=settings.anthropic_model,
                max_tokens=1200,
                system=SYSTEM,
                output_config={"effort": "low"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                messages=[{"role": "user", "content": "Fact sheet:\n" + json.dumps(facts, default=str)}],
            )
            if resp.stop_reason != "refusal":
                text = "".join(b.text for b in resp.content if b.type == "text").strip()
                if text:
                    return {"source": "claude", "model": resp.model, "text": text}
        except Exception as exc:  # network, auth, rate limit: never break the page
            log.warning("Claude analyst failed, using offline template: %s", exc)
    return {"source": "offline", "model": "template", "text": offline_explanation(facts)}
