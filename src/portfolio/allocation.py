from __future__ import annotations


def expected_portfolio_return(weights: dict[str, float], expected_returns: dict[str, float]) -> float:
    return sum(weights[a] * expected_returns[a] for a in weights)
