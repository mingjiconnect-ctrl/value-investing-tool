from __future__ import annotations

from pathlib import Path

from src.data.loaders import load_yaml
from src.data.schemas import ScenarioAssumptions


SCENARIO_FILES = {
    "base": "config/assumptions/base.yaml",
    "bull": "config/assumptions/bull.yaml",
    "black_swan": "config/assumptions/black_swan.yaml",
}


def load_scenario(name: str) -> ScenarioAssumptions:
    data = load_yaml(Path(SCENARIO_FILES[name]))
    return ScenarioAssumptions(**data)


def load_all_scenarios() -> dict[str, ScenarioAssumptions]:
    return {k: load_scenario(k) for k in SCENARIO_FILES}
