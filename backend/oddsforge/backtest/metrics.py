"""Probability-quality metrics for 3-way soccer outcomes. Accuracy is reported but never used
to choose a model: a model can pick more winners and still be worse for betting."""

from __future__ import annotations

import numpy as np


def outcome_index(hg, ag) -> np.ndarray:
    hg, ag = np.asarray(hg), np.asarray(ag)
    return np.where(hg > ag, 0, np.where(hg == ag, 1, 2))


def log_loss(P: np.ndarray, y: np.ndarray) -> float:
    return float(-np.log(np.clip(P[np.arange(len(y)), y], 1e-12, 1)).mean())


def brier(P: np.ndarray, y: np.ndarray) -> float:
    Y = np.eye(P.shape[1])[y]
    return float(((P - Y) ** 2).sum(axis=1).mean())


def rps(P: np.ndarray, y: np.ndarray) -> float:
    """Ranked probability score: respects the order home > draw > away, so predicting a draw
    when the home team wins is penalised less than predicting an away win."""
    Y = np.eye(P.shape[1])[y]
    cp, cy = np.cumsum(P, axis=1)[:, :-1], np.cumsum(Y, axis=1)[:, :-1]
    return float(((cp - cy) ** 2).sum(axis=1).mean() / (P.shape[1] - 1))


def accuracy(P: np.ndarray, y: np.ndarray) -> float:
    return float((P.argmax(axis=1) == y).mean())


def reliability(p: np.ndarray, hit: np.ndarray, bins: int = 10) -> list[dict]:
    """Reliability curve with equal-count bins (equal-width bins leave the tails nearly empty)."""
    order = np.argsort(p)
    out = []
    for chunk in np.array_split(order, bins):
        if len(chunk) == 0:
            continue
        out.append({"pred": float(p[chunk].mean()), "obs": float(hit[chunk].mean()), "n": int(len(chunk))})
    return out


def ece(p: np.ndarray, hit: np.ndarray, bins: int = 10) -> float:
    rel = reliability(p, hit, bins)
    n = sum(r["n"] for r in rel)
    return float(sum(r["n"] * abs(r["pred"] - r["obs"]) for r in rel) / n)


def summary(P: np.ndarray, y: np.ndarray) -> dict:
    hits = np.eye(3)[y]
    return {
        "n": int(len(y)),
        "log_loss": log_loss(P, y),
        "brier": brier(P, y),
        "rps": rps(P, y),
        "accuracy": accuracy(P, y),
        "ece": float(np.mean([ece(P[:, k], hits[:, k]) for k in range(3)])),
        "mean_pred": {
            "home": float(P[:, 0].mean()),
            "draw": float(P[:, 1].mean()),
            "away": float(P[:, 2].mean()),
        },
        "observed": {
            "home": float(hits[:, 0].mean()),
            "draw": float(hits[:, 1].mean()),
            "away": float(hits[:, 2].mean()),
        },
    }


def bootstrap_roi(
    profits: np.ndarray, stakes: np.ndarray, n: int = 2000, seed: int = 0
) -> tuple[float, float]:
    if len(profits) == 0:
        return 0.0, 0.0
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(profits), size=(n, len(profits)))
    rois = profits[idx].sum(axis=1) / stakes[idx].sum(axis=1)
    return float(np.percentile(rois, 2.5)), float(np.percentile(rois, 97.5))
