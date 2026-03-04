from __future__ import annotations

import numpy as np


def simulate_valuation_driver(
    base_growth: float,
    base_margin: float,
    base_wacc: float,
    n_sims: int = 1000,
    seed: int = 42,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    growth = rng.normal(base_growth, 0.03, n_sims)
    margin = rng.normal(base_margin, 0.02, n_sims)
    wacc = rng.normal(base_wacc, 0.01, n_sims)
    return (growth * 0.4 + margin * 0.5 - wacc * 0.6) * 100


def simulate_price_path_stub() -> None:
    return None
