"""Settlement rules for 1X2, Asian handicap (incl. quarter lines), totals and BTTS.

A leg settles to a payout *factor* applied to its stake:
  win -> price, loss -> 0, push/void -> 1,
  half win -> (price + 1) / 2, half loss -> 0.5.
Quarter lines (e.g. -0.75) split the stake across the two neighbouring lines (-0.5 and -1.0).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Outcome:
    result: str  # won | lost | void | half_won | half_lost
    factor: float


def _split(line: float) -> tuple[float, float]:
    """-0.75 -> (-0.5, -1.0); -0.5 -> (-0.5, -0.5); 0.25 -> (0.0, 0.5)."""
    q = round(line * 4)
    if q % 2 == 0:  # whole or half line
        return line, line
    lo, hi = (q - 1) / 4, (q + 1) / 4
    return lo, hi


def _half(margin: float) -> int:
    return 1 if margin > 1e-9 else (-1 if margin < -1e-9 else 0)


def _combine(parts: tuple[int, int], price: float) -> Outcome:
    f = sum(price if r == 1 else (1.0 if r == 0 else 0.0) for r in parts) / 2
    s = sorted(parts)
    if s == [1, 1]:
        res = "won"
    elif s == [-1, -1]:
        res = "lost"
    elif s == [0, 0]:
        res = "void"
    elif s == [0, 1]:
        res = "half_won"
    elif s == [-1, 0]:
        res = "half_lost"
    else:  # cannot happen with adjacent quarter lines
        res = "void"
    return Outcome(res, f)


def settle_asian(home_goals: int, away_goals: int, side: str, home_line: float, price: float) -> Outcome:
    """`home_line` is the handicap applied to the home team (-0.5 = home must win)."""
    diff = home_goals - away_goals
    a, b = _split(home_line)
    if side == "home":
        parts = (_half(diff + a), _half(diff + b))
    elif side == "away":
        parts = (_half(-diff - a), _half(-diff - b))
    else:
        raise ValueError(side)
    return _combine(parts, price)


def settle_total(home_goals: int, away_goals: int, side: str, line: float, price: float) -> Outcome:
    total = home_goals + away_goals
    a, b = _split(line)
    if side == "over":
        parts = (_half(total - a), _half(total - b))
    elif side == "under":
        parts = (_half(a - total), _half(b - total))
    else:
        raise ValueError(side)
    return _combine(parts, price)


def settle_1x2(home_goals: int, away_goals: int, side: str, price: float) -> Outcome:
    actual = "home" if home_goals > away_goals else ("away" if away_goals > home_goals else "draw")
    return Outcome("won", price) if side == actual else Outcome("lost", 0.0)


def settle_btts(home_goals: int, away_goals: int, side: str, price: float) -> Outcome:
    yes = home_goals > 0 and away_goals > 0
    return Outcome("won", price) if (side == "yes") == yes else Outcome("lost", 0.0)


def settle_leg(market: str, selection: str, line: float | None, price: float, hg: int, ag: int) -> Outcome:
    if market == "1x2":
        return settle_1x2(hg, ag, selection, price)
    if market == "ah":
        assert line is not None
        return settle_asian(hg, ag, selection, line, price)
    if market == "ou":
        assert line is not None
        return settle_total(hg, ag, selection, line, price)
    if market == "btts":
        return settle_btts(hg, ag, selection, price)
    raise ValueError(f"unknown market {market}")
