from __future__ import annotations

from dataclasses import asdict

import numpy as np
import pandas as pd

from src.core.types import BoundaryCondition
from src.data.normalize.adjustments import apply_one_off_adjustments
from src.data.normalize.financials import normalize_financials
from src.data.normalize.owner_earnings import calc_owner_earnings
from src.pipelines.run_portfolio import run_portfolio
from src.portfolio.allocation import expected_portfolio_return
from src.reporting.charts import save_sensitivity_heatmap
from src.reporting.export import export_csv, export_json
from src.reporting.render_md import render_report
from src.risk.drawdown import drawdown_distribution
from src.risk.monte_carlo import simulate_valuation_driver
from src.valuation.dcf import dcf_two_stage
from src.valuation.scenarios import load_all_scenarios
from src.valuation.sensitivity import wacc_g_sensitivity


def _sample_expected_returns(prices: pd.DataFrame) -> tuple[dict[str, float], np.ndarray]:
    pivot = prices.pivot(index="date", columns="asset", values="price").sort_index()
    rets = pivot.pct_change().dropna()
    exp_ret = rets.mean().to_dict()
    cov = rets.cov().values
    return {str(k): float(v) for k, v in exp_ret.items()}, cov


def run_single_stock(provider, settings: dict, output_dir: str = "outputs") -> dict:
    fundamentals = provider.get_fundamentals()
    fundamentals = normalize_financials(fundamentals)
    fundamentals = apply_one_off_adjustments(fundamentals)
    fundamentals = calc_owner_earnings(
        fundamentals,
        maint_capex_ratio=settings["maint_capex_ratio"],
        sbc_adjust_ratio=settings["sbc_adjust_ratio"],
    )
    export_csv(fundamentals, f"{output_dir}/normalized_financials.csv")

    latest = fundamentals.iloc[-1]
    scenarios = load_all_scenarios()
    valuation_results = {}
    for name, sc in scenarios.items():
        valuation_results[name] = dcf_two_stage(
            base_revenue=float(latest["revenue"]),
            growth=sc.revenue_growth,
            margins=sc.fcf_margin,
            wacc=sc.wacc,
            terminal_g=sc.terminal_g,
            shares_outstanding=float(latest["shares_outstanding"]),
            net_debt=float(latest["net_debt"]),
            mos_discount=settings["mos_discount"],
            terminal_method="gordon",
            exit_multiple=sc.exit_multiple,
        )

    sens = wacc_g_sensitivity(
        base_revenue=float(latest["revenue"]),
        growth=scenarios["base"].revenue_growth,
        margins=scenarios["base"].fcf_margin,
        wacc_grid=[0.08, 0.09, 0.1, 0.11],
        g_grid=[0.02, 0.03, 0.04],
        shares_outstanding=float(latest["shares_outstanding"]),
        net_debt=float(latest["net_debt"]),
    )
    export_csv(sens, f"{output_dir}/sensitivity_wacc_g.csv")
    save_sensitivity_heatmap(sens, f"{output_dir}/charts/sensitivity_wacc_g.png")

    mc = simulate_valuation_driver(
        base_growth=float(np.mean(scenarios["base"].revenue_growth)),
        base_margin=float(np.mean(scenarios["base"].fcf_margin)),
        base_wacc=scenarios["base"].wacc,
    )
    rng = np.random.default_rng(0)
    paths = np.cumprod(1 + rng.normal(0.0005, 0.02, size=(300, 252)), axis=1)
    dd = drawdown_distribution(paths)

    prices = provider.get_prices()
    exp_rets, cov = _sample_expected_returns(prices)
    kelly_w = run_portfolio(exp_rets, cov, cap=0.6)
    portfolio_ret = expected_portfolio_return(kelly_w, exp_rets)

    boundaries = [
        BoundaryCondition("Discount rate", "WACC > terminal_g", "Gordon denominator must be positive"),
        BoundaryCondition("Unit consistency", "currency=USD, time_unit=year", "Avoid mixed-unit artifacts"),
        BoundaryCondition("SBC treatment", "sbc_adjust_ratio in [0,1]", "Defines dilution conservatism"),
    ]

    payload = {
        "scenarios": {k: asdict(v) for k, v in valuation_results.items()},
        "mc_stats": {
            "p5": float(np.percentile(mc, 5)),
            "p50": float(np.percentile(mc, 50)),
            "p95": float(np.percentile(mc, 95)),
        },
        "drawdown_stats": {
            "p5": float(np.percentile(dd, 5)),
            "p50": float(np.percentile(dd, 50)),
            "p95": float(np.percentile(dd, 95)),
        },
        "portfolio": {"kelly_weights": kelly_w, "expected_return": float(portfolio_ret)},
    }
    export_json(payload, f"{output_dir}/valuation.json")

    report_context = {
        "scenarios": valuation_results,
        "explicit_years": settings["explicit_years"],
        "mc_stats": payload["mc_stats"],
        "dd_stats": payload["drawdown_stats"],
        "boundaries": boundaries,
        "kelly_weights": payload["portfolio"]["kelly_weights"],
        "portfolio_expected_return": payload["portfolio"]["expected_return"],
    }
    render_report(report_context, f"{output_dir}/report.md")
    return payload
