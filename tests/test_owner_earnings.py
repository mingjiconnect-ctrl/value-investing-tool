import pandas as pd

from src.data.normalize.owner_earnings import calc_owner_earnings


def _df():
    return pd.DataFrame(
        {
            "year": [2023, 2024],
            "net_income": [100, 110],
            "da": [20, 22],
            "capex": [30, 32],
            "delta_working_capital": [5, 6],
            "sbc": [10, 10],
        }
    )


def test_owner_earnings_basic():
    out = calc_owner_earnings(_df(), maint_capex_ratio=0.5, sbc_adjust_ratio=1.0)
    assert round(out.iloc[0]["owner_earnings"], 2) == 90


def test_owner_earnings_sbc_ratio():
    out = calc_owner_earnings(_df(), maint_capex_ratio=0.5, sbc_adjust_ratio=0.5)
    assert out.iloc[0]["owner_earnings"] > 90
