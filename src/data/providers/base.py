from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class DataProvider(ABC):
    @abstractmethod
    def get_fundamentals(self) -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    def get_prices(self) -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    def get_macro(self) -> pd.DataFrame:
        raise NotImplementedError
