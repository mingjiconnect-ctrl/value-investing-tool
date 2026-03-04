import pytest

from src.core.errors import ValidationError
from src.valuation.dcf import dcf_three_stage, dcf_two_stage


def test_dcf_two_stage_output_positive():
    out = dcf_two_stage(1000, [0.1] * 5, [0.15] * 5, 0.1, 0.03, 100, 10)
    assert out.ev > 0
    assert out.intrinsic_value_per_share > 0


def test_dcf_invalid_boundary():
    with pytest.raises(ValidationError):
        dcf_two_stage(1000, [0.1] * 5, [0.15] * 5, 0.03, 0.03, 100, 10)


def test_dcf_three_stage_runs():
    out = dcf_three_stage(1000, [0.1] * 3, [0.15] * 3, [0.05] * 2, [0.16] * 2, 0.1, 0.03, 100, 10)
    assert out.mos_buy_price > 0
