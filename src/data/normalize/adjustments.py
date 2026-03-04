from __future__ import annotations

import pandas as pd


def apply_one_off_adjustments(df: pd.DataFrame, adjustments: dict[int, float] | None = None) -> pd.DataFrame:
    out = df.copy()
    out["one_off_adjustment"] = out["year"].map(adjustments or {}).fillna(0.0)
    return out


def adjust_sbc(sbc: float, ratio: float = 1.0) -> float:
    return sbc * ratio


def lease_adjustment_stub(value: float) -> float:
    return value
