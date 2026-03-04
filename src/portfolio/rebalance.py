from __future__ import annotations


def rebalance_to_target(current: dict[str, float], target: dict[str, float]) -> dict[str, float]:
    return {k: target[k] - current.get(k, 0.0) for k in target}
