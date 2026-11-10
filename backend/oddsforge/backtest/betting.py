"""Betting simulation on top of walk-forward predictions.

Rules that keep the numbers honest:
- one bet per match per market (the best-EV side), so correlated sides are never stacked;
- the price we bet at must exist at decision time (`timing`), and CLV is measured against a
  *later* price from a sharp book (Pinnacle close), with its vig removed by the power method;
- EV above `max_edge` is skipped: in a mature market a 20% "edge" is far more likely to be a
  model error (missing lineup news, a data glitch) than a real opportunity;
- ROI comes with a bootstrap 95% interval, because a few hundred bets cannot prove much.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..markets.derive import asian_breakdown, ev_from_breakdown, total_breakdown
from ..markets.odds import devig, kelly_fraction
from ..markets.settlement import settle_leg
from ..model.dixon_coles import score_matrix
from .metrics import bootstrap_roi


@dataclass
class Strategy:
    name: str
    market: str = "1x2"  # 1x2 | ah | ou
    book: str = "pinnacle"
    timing: str = "close"
    min_edge: float = 0.03
    max_edge: float = 0.25
    staking: str = "flat"  # flat | kelly
    clv_book: str | None = None  # e.g. "pinnacle" with timing close


def quotes_frame(rows) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["match_id", "market", "line", "book", "timing", "a", "b", "c"])


def _index(q: pd.DataFrame, market: str, book: str, timing: str) -> dict[int, tuple]:
    sub = q[(q.market == market) & (q.book == book) & (q.timing == timing)]
    return {int(r.match_id): (r.line, r.a, r.b, r.c) for r in sub.itertuples(index=False)}


def candidate_bets(wf: pd.DataFrame, q: pd.DataFrame, st: Strategy) -> pd.DataFrame:
    prices = _index(q, st.market, st.book, st.timing)
    close = _index(q, st.market, st.clv_book, "close") if st.clv_book else {}
    rows = []
    for r in wf.itertuples(index=False):
        if r.id not in prices or np.isnan(r.hg):
            continue
        line, a, b, c = prices[r.id]
        m = score_matrix(r.lh, r.la, r.rho)
        options = []  # (selection, line, price, model_prob_or_None, ev, closing fair prob or None)
        if st.market == "1x2":
            probs = (r.p_home, r.p_draw, r.p_away)
            cl = close.get(r.id)
            fair = devig([cl[1], cl[2], cl[3]]) if cl else None
            for k, (sel, price) in enumerate(zip(("home", "draw", "away"), (a, b, c), strict=True)):
                options.append((sel, None, price, probs[k], probs[k] * price - 1, fair[k] if fair else None))
        elif st.market in ("ah", "ou"):
            cl = close.get(r.id)
            same_line = cl is not None and cl[0] == line
            fair = devig([cl[1], cl[2]]) if same_line else None
            sides = ("home", "away") if st.market == "ah" else ("over", "under")
            for k, (sel, price) in enumerate(zip(sides, (a, b), strict=True)):
                bd = asian_breakdown(m, line, sel) if st.market == "ah" else total_breakdown(m, line, sel)
                options.append(
                    (sel, line, price, None, ev_from_breakdown(bd, price), fair[k] if fair else None)
                )
        sel, ln, price, prob, ev, fair_close = max(options, key=lambda o: o[4])
        out = settle_leg(st.market, sel, ln, price, int(r.hg), int(r.ag))
        rows.append(
            {
                "id": r.id,
                "season": r.season,
                "kickoff": r.kickoff,
                "selection": sel,
                "line": ln,
                "price": price,
                "model_prob": prob,
                "ev": ev,
                "factor": out.factor,
                "result": out.result,
                "clv": (price * fair_close - 1) if fair_close else np.nan,
            }
        )
    return pd.DataFrame(rows)


def simulate(cands: pd.DataFrame, st: Strategy, bankroll0: float = 100.0) -> dict:
    if cands.empty:
        return {"strategy": st.__dict__, "bets": 0}
    bets = cands[(cands.ev >= st.min_edge) & (cands.ev <= st.max_edge)].sort_values("kickoff").copy()
    if st.staking == "flat":
        bets["stake"] = 1.0
    else:  # quarter Kelly on a running bankroll, settled in kickoff order
        bank, stakes = bankroll0, []
        for r in bets.itertuples(index=False):
            p_eff = (1 + r.ev) / r.price  # EV-equivalent win probability (handles pushes)
            s = bank * kelly_fraction(p_eff, r.price, fraction=0.25, cap=0.025)
            stakes.append(s)
            bank += s * (r.factor - 1)
        bets["stake"] = stakes
    bets["profit"] = bets["stake"] * (bets["factor"] - 1)
    n = len(bets)
    staked = float(bets["stake"].sum())
    lo, hi = bootstrap_roi(bets["profit"].to_numpy(), bets["stake"].to_numpy()) if n else (0.0, 0.0)
    clv = bets["clv"].dropna()
    curve = bets[["kickoff", "profit"]].assign(cum=lambda d: d["profit"].cumsum())
    step = max(1, n // 120)
    return {
        "strategy": st.__dict__,
        "bets": n,
        "staked": staked,
        "profit": float(bets["profit"].sum()),
        "roi": float(bets["profit"].sum() / staked) if staked else 0.0,
        "roi_ci95": [lo, hi],
        "hit_rate": float((bets["factor"] > 1).mean()) if n else 0.0,
        "avg_price": float(bets["price"].mean()) if n else 0.0,
        "avg_model_ev": float(bets["ev"].mean()) if n else 0.0,
        "clv_mean": float(clv.mean()) if len(clv) else None,
        "clv_positive_share": float((clv > 0).mean()) if len(clv) else None,
        "final_bankroll": float(bankroll0 + bets["profit"].sum()) if st.staking == "kelly" else None,
        "curve": [
            {"t": str(r.kickoff)[:10], "cum": round(float(r.cum), 3)} for r in curve.iloc[::step].itertuples()
        ],
    }


def by_bucket(cands: pd.DataFrame, col: str, edges: list[float]) -> list[dict]:
    out = []
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        b = cands[(cands[col] >= lo) & (cands[col] < hi)]
        if len(b) == 0:
            continue
        prof = (b["factor"] - 1).sum()
        lo_ci, hi_ci = bootstrap_roi((b["factor"] - 1).to_numpy(), np.ones(len(b)))
        clv = b["clv"].dropna()
        out.append(
            {
                "bucket": f"{lo:g} to {hi:g}",
                "bets": int(len(b)),
                "roi": float(prof / len(b)),
                "roi_ci95": [lo_ci, hi_ci],
                "avg_ev": float(b["ev"].mean()),
                "clv_mean": float(clv.mean()) if len(clv) else None,
            }
        )
    return out
