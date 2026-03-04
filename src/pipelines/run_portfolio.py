from __future__ import annotations

import numpy as np

from src.portfolio.kelly import kelly_weights


def run_portfolio(expected_returns: dict[str, float], cov: np.ndarray, cap: float = 0.6) -> dict[str, float]:
    assets = list(expected_returns)
    mu = np.array([expected_returns[a] for a in assets])
    weights = kelly_weights(mu, cov, cap=cap)
    return {a: float(w) for a, w in zip(assets, weights, strict=True)}
