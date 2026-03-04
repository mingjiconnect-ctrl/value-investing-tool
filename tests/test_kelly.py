import numpy as np

from src.portfolio.kelly import kelly_weights


def test_kelly_non_negative():
    mu = np.array([0.1, 0.08])
    sigma = np.array([[0.04, 0.01], [0.01, 0.03]])
    w = kelly_weights(mu, sigma, cap=0.6)
    assert (w >= 0).all()


def test_kelly_sum_to_one():
    mu = np.array([0.1, 0.08, 0.07])
    sigma = np.eye(3) * 0.05
    w = kelly_weights(mu, sigma, cap=0.6)
    assert abs(w.sum() - 1) < 1e-6


def test_kelly_cap_respected():
    mu = np.array([0.2, 0.01])
    sigma = np.eye(2) * 0.03
    w = kelly_weights(mu, sigma, cap=0.6)
    assert (w <= 0.600001).all()
