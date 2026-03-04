from __future__ import annotations

STRESS_PRESETS = {
    "1930s": {"growth_shock": -0.15, "margin_shock": -0.08, "wacc_shock": 0.03},
    "2008": {"growth_shock": -0.1, "margin_shock": -0.05, "wacc_shock": 0.02},
    "2022": {"growth_shock": -0.05, "margin_shock": -0.03, "wacc_shock": 0.015},
}


def apply_stress(base: dict[str, float], preset: str) -> dict[str, float]:
    shock = STRESS_PRESETS[preset]
    return {
        "growth": base["growth"] + shock["growth_shock"],
        "margin": base["margin"] + shock["margin_shock"],
        "wacc": base["wacc"] + shock["wacc_shock"],
    }
