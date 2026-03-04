from __future__ import annotations


def sotp_value(segments: dict[str, float], net_debt: float) -> dict[str, float]:
    segment_total = sum(segments.values())
    return {
        "segment_value": segment_total,
        "equity_value": segment_total - net_debt,
    }
