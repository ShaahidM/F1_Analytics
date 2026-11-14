"""JSON-safe conversion of pandas objects (NaN/NA → null, timestamps → ISO strings)."""

from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import pandas as pd


def value(v):
    if v is None or v is pd.NA or v is pd.NaT:
        return None
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.isoformat()
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, (list, tuple, np.ndarray)):
        return [value(x) for x in v]
    return v


def row(r: pd.Series) -> dict:
    return {k: value(v) for k, v in r.items()}


def frame(df: pd.DataFrame, columns: list[str] | None = None) -> list[dict]:
    cols = [c for c in (columns or df.columns) if c in df.columns and not c.startswith("_")]
    return [{c: value(v) for c, v in zip(cols, vals)} for vals in df[cols].itertuples(index=False, name=None)]
