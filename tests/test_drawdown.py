import numpy as np

from src.risk.drawdown import drawdown_distribution, max_drawdown


def test_max_drawdown_negative():
    series = np.array([1.0, 1.1, 0.9, 0.8, 0.95])
    assert max_drawdown(series) < 0


def test_drawdown_distribution_shape():
    paths = np.array([[1.0, 0.9, 0.8], [1.0, 1.1, 1.2]])
    dd = drawdown_distribution(paths)
    assert dd.shape == (2,)
