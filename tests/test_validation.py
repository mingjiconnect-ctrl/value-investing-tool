import pytest

from src.core.errors import ValidationError
from src.core.validation import validate_discount_vs_growth, validate_units, validate_weights


def test_validate_discount_ok():
    validate_discount_vs_growth(0.1, 0.03)


def test_validate_discount_fail():
    with pytest.raises(ValidationError):
        validate_discount_vs_growth(0.03, 0.03)


def test_validate_weights_ok():
    validate_weights({"a": 0.5, "b": 0.5}, cap=0.6)


def test_validate_weights_fail_sum():
    with pytest.raises(ValidationError):
        validate_weights({"a": 0.4, "b": 0.5}, cap=0.6)


def test_validate_units_ok():
    validate_units("USD", "year", 0.2)


def test_validate_units_fail():
    with pytest.raises(ValidationError):
        validate_units("CNY", "year", 0.2)
