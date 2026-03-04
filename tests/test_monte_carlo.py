import numpy as np

from src.risk.monte_carlo import simulate_valuation_driver


def test_mc_reproducible():
    a = simulate_valuation_driver(0.08, 0.15, 0.09, n_sims=100, seed=1)
    b = simulate_valuation_driver(0.08, 0.15, 0.09, n_sims=100, seed=1)
    assert np.allclose(a, b)


def test_mc_length():
    a = simulate_valuation_driver(0.08, 0.15, 0.09, n_sims=250)
    assert len(a) == 250
