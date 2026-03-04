from __future__ import annotations

from dataclasses import dataclass

from src.core.validation import validate_discount_vs_growth


@dataclass
class DCFOutput:
    ev: float
    equity_value: float
    intrinsic_value_per_share: float
    mos_buy_price: float
    terminal_value: float


def _project_fcfs(base_revenue: float, growth: list[float], margins: list[float]) -> list[float]:
    rev = base_revenue
    fcfs: list[float] = []
    for g, m in zip(growth, margins, strict=True):
        rev *= 1 + g
        fcfs.append(rev * m)
    return fcfs


def _terminal_value_gordon(last_fcf: float, wacc: float, terminal_g: float) -> float:
    validate_discount_vs_growth(wacc, terminal_g)
    return last_fcf * (1 + terminal_g) / (wacc - terminal_g)


def dcf_two_stage(
    base_revenue: float,
    growth: list[float],
    margins: list[float],
    wacc: float,
    terminal_g: float,
    shares_outstanding: float,
    net_debt: float,
    mos_discount: float = 0.25,
    terminal_method: str = "gordon",
    exit_multiple: float = 12.0,
) -> DCFOutput:
    fcfs = _project_fcfs(base_revenue, growth, margins)
    terminal_value = (
        _terminal_value_gordon(fcfs[-1], wacc, terminal_g)
        if terminal_method == "gordon"
        else fcfs[-1] * exit_multiple
    )
    ev = sum(f / ((1 + wacc) ** (i + 1)) for i, f in enumerate(fcfs)) + terminal_value / (
        (1 + wacc) ** len(fcfs)
    )
    equity_value = ev - net_debt
    per_share = equity_value / shares_outstanding
    return DCFOutput(
        ev=float(ev),
        equity_value=float(equity_value),
        intrinsic_value_per_share=float(per_share),
        mos_buy_price=float(per_share * (1 - mos_discount)),
        terminal_value=float(terminal_value),
    )


def dcf_three_stage(
    base_revenue: float,
    growth_stage1: list[float],
    margins_stage1: list[float],
    growth_stage2: list[float],
    margins_stage2: list[float],
    wacc: float,
    terminal_g: float,
    shares_outstanding: float,
    net_debt: float,
) -> DCFOutput:
    growth = growth_stage1 + growth_stage2
    margins = margins_stage1 + margins_stage2
    return dcf_two_stage(
        base_revenue,
        growth,
        margins,
        wacc,
        terminal_g,
        shares_outstanding,
        net_debt,
    )
