from __future__ import annotations


def ev_ebitda(ebitda: float, multiple: float, net_debt: float) -> float:
    return ebitda * multiple - net_debt
