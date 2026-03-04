from pathlib import Path

from src.pipelines.run_example import run_example


def test_run_example_generates_outputs():
    run_example()
    assert Path("outputs/report.md").exists()
    assert Path("outputs/valuation.json").exists()
    assert Path("outputs/charts/sensitivity_wacc_g.png").exists()


def test_run_example_payload_keys():
    out = run_example()
    assert "scenarios" in out
    assert "mc_stats" in out
    assert "drawdown_stats" in out
