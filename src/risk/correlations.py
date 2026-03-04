from __future__ import annotations

import pandas as pd


def correlation_matrix(returns: pd.DataFrame) -> pd.DataFrame:
    return returns.corr()
