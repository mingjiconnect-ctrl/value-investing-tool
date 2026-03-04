from __future__ import annotations

from src.core.errors import ValidationError


def validate_discount_vs_growth(wacc: float, terminal_g: float) -> None:
    if wacc <= terminal_g:
        raise ValidationError("WACC must be greater than terminal growth rate.")


def validate_weights(weights: dict[str, float], cap: float) -> None:
    total = sum(weights.values())
    if any(w < 0 for w in weights.values()):
        raise ValidationError("Weights must be non-negative.")
    if any(w > cap for w in weights.values()):
        raise ValidationError("Weights exceed cap.")
    if abs(total - 1.0) > 1e-6:
        raise ValidationError("Weights must sum to 1.")


def validate_units(currency: str, time_unit: str, tax_rate: float) -> None:
    if currency != "USD":
        raise ValidationError("Only USD is supported in example implementation.")
    if time_unit != "year":
        raise ValidationError("Only annual data is supported in example implementation.")
    if not (0 <= tax_rate <= 1):
        raise ValidationError("Tax rate must be in [0,1].")
