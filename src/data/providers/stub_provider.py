from __future__ import annotations

from pathlib import Path

from src.data.loaders import load_csv
from src.data.providers.base import DataProvider


class StubDataProvider(DataProvider):
    def __init__(self, data_dir: str = "data/example") -> None:
        self.data_dir = Path(data_dir)

    def get_fundamentals(self):
        return load_csv(self.data_dir / "fundamentals.csv")

    def get_prices(self):
        return load_csv(self.data_dir / "prices.csv")

    def get_macro(self):
        return load_csv(self.data_dir / "macro.csv")
