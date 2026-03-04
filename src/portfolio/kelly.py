from __future__ import annotations

import numpy as np


def kelly_weights(mu: np.ndarray, sigma: np.ndarray, cap: float = 0.6) -> np.ndarray:
    raw = np.linalg.pinv(sigma) @ mu
    raw = np.clip(raw, 0, None)
    if raw.sum() == 0:
        raw = np.ones_like(raw)
    w = raw / raw.sum()
    w = np.minimum(w, cap)
    if w.sum() == 0:
        return np.ones_like(w) / len(w)
    return w / w.sum()
