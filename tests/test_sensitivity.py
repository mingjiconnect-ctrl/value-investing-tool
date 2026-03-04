from src.valuation.sensitivity import growth_margin_sensitivity, wacc_g_sensitivity


def test_wacc_g_shape():
    df = wacc_g_sensitivity(1000, [0.1] * 5, [0.15] * 5, [0.09, 0.1], [0.02, 0.03], 100, 10)
    assert len(df) == 4


def test_growth_margin_shape():
    df = growth_margin_sensitivity(
        1000,
        [0.1] * 5,
        [0.15] * 5,
        [-0.01, 0.0, 0.01],
        [-0.01, 0.0, 0.01],
        0.1,
        0.03,
        100,
        10,
    )
    assert len(df) == 9
