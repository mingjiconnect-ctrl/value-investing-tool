from __future__ import annotations

import pandas as pd

from src.data.normalize.adjustments import adjust_sbc


def calc_owner_earnings(
    df: pd.DataFrame,
    maint_capex_ratio: float = 0.4,
    sbc_adjust_ratio: float = 1.0,
) -> pd.DataFrame:
    out = df.copy()
    out["maint_capex"] = out["capex"] * maint_capex_ratio
    out["sbc_adjust"] = out["sbc"].apply(lambda x: adjust_sbc(float(x), ratio=sbc_adjust_ratio))
    out["owner_earnings"] = (
        out["net_income"]
        + out["da"]
        - out["maint_capex"]
        - out["delta_working_capital"]
        - out["sbc_adjust"]
        + out.get("one_off_adjustment", 0.0)
    )
    return out
