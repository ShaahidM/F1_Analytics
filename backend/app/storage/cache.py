"""Parquet store for processed / bulky tables (telemetry). Raw JSON caching lives in sources/http.py."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pandas as pd

from app.config import PARQUET_DIR


def parquet_path(source: str, session_key: str, table: str) -> Path:
    return PARQUET_DIR / source / str(session_key) / f"{table}.parquet"


def cached_frame(path: Path, build: Callable[[], pd.DataFrame], persist: bool = True) -> pd.DataFrame:
    """Return the Parquet at `path`, building (and optionally persisting) it on a miss."""
    if path.exists():
        return pd.read_parquet(path)
    df = build()
    if persist:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        df.to_parquet(tmp, index=False)
        tmp.replace(path)
    return df
