from __future__ import annotations

import pandas as pd

from src.core.validation import validate_units


def normalize_financials(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out = out.sort_values("year").reset_index(drop=True)
    latest = out.iloc[-1]
    validate_units(str(latest["currency"]), str(latest["time_unit"]), float(latest["tax_rate"]))
    out["delta_working_capital"] = out["working_capital"].diff().fillna(0.0)
    return out
