from __future__ import annotations

import pandas as pd

from src.valuation.dcf import dcf_two_stage


def wacc_g_sensitivity(
    base_revenue: float,
    growth: list[float],
    margins: list[float],
    wacc_grid: list[float],
    g_grid: list[float],
    shares_outstanding: float,
    net_debt: float,
) -> pd.DataFrame:
    rows: list[dict[str, float]] = []
    for wacc in wacc_grid:
        for g in g_grid:
            result = dcf_two_stage(
                base_revenue,
                growth,
                margins,
                wacc,
                g,
                shares_outstanding,
                net_debt,
            )
            rows.append({"wacc": wacc, "terminal_g": g, "value_per_share": result.intrinsic_value_per_share})
    return pd.DataFrame(rows)


def growth_margin_sensitivity(
    base_revenue: float,
    growth_base: list[float],
    margin_base: list[float],
    growth_shift: list[float],
    margin_shift: list[float],
    wacc: float,
    terminal_g: float,
    shares_outstanding: float,
    net_debt: float,
) -> pd.DataFrame:
    rows = []
    for gs in growth_shift:
        for ms in margin_shift:
            growth = [g + gs for g in growth_base]
            margin = [m + ms for m in margin_base]
            res = dcf_two_stage(base_revenue, growth, margin, wacc, terminal_g, shares_outstanding, net_debt)
            rows.append({"growth_shift": gs, "margin_shift": ms, "value_per_share": res.intrinsic_value_per_share})
    return pd.DataFrame(rows)
