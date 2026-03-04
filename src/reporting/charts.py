from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def save_sensitivity_heatmap(df: pd.DataFrame, path: str) -> None:
    pivot = df.pivot(index="wacc", columns="terminal_g", values="value_per_share")
    fig, ax = plt.subplots(figsize=(6, 4))
    im = ax.imshow(pivot.values, aspect="auto")
    ax.set_xticks(range(len(pivot.columns)), labels=[f"{x:.2%}" for x in pivot.columns])
    ax.set_yticks(range(len(pivot.index)), labels=[f"{x:.2%}" for x in pivot.index])
    ax.set_xlabel("Terminal g")
    ax.set_ylabel("WACC")
    plt.colorbar(im, ax=ax)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
