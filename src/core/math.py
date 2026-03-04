from __future__ import annotations

import numpy as np


def cagr(start: float, end: float, periods: int) -> float:
    if start <= 0 or periods <= 0:
        return 0.0
    return (end / start) ** (1 / periods) - 1


def npv(cashflows: list[float], rate: float) -> float:
    return float(np.sum([cf / ((1 + rate) ** (i + 1)) for i, cf in enumerate(cashflows)]))
