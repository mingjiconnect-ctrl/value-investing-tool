from __future__ import annotations

import numpy as np


def max_drawdown(series: np.ndarray) -> float:
    running_max = np.maximum.accumulate(series)
    dd = series / running_max - 1
    return float(dd.min())


def drawdown_distribution(paths: np.ndarray) -> np.ndarray:
    return np.array([max_drawdown(path) for path in paths])
