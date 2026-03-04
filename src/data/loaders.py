from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import yaml


def load_csv(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path)


def load_excel(path: str | Path, sheet_name: str | int = 0) -> pd.DataFrame:
    return pd.read_excel(path, sheet_name=sheet_name)


def load_manual_input(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def load_yaml(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)
