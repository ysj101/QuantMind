"""Parquet 読み書きヘルパ."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def write_parquet(df: pd.DataFrame, path: str | Path, *, compression: str = "snappy") -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, compression=compression, index=False)
    return p


def read_parquet(path: str | Path) -> pd.DataFrame:
    return pd.read_parquet(path)
