from __future__ import annotations

from pydantic import BaseModel, Field


class FundamentalsRow(BaseModel):
    year: int
    revenue: float
    net_income: float
    da: float
    capex: float
    working_capital: float
    sbc: float
    shares_outstanding: float = Field(gt=0)
    net_debt: float
    currency: str
    time_unit: str
    tax_rate: float = Field(ge=0, le=1)


class ScenarioAssumptions(BaseModel):
    name: str
    revenue_growth: list[float]
    fcf_margin: list[float]
    wacc: float
    terminal_g: float
    exit_multiple: float
