from __future__ import annotations

from src.data.loaders import load_yaml
from src.data.providers.stub_provider import StubDataProvider
from src.pipelines.run_single_stock import run_single_stock


def run_example() -> dict:
    settings = load_yaml("config/settings.yaml")
    provider = StubDataProvider()
    return run_single_stock(provider, settings)
