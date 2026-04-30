"""株価取得 → price_daily UPSERT."""

from __future__ import annotations

from datetime import date

import pandas as pd

from quantmind.data.prices.base import PriceSource
from quantmind.storage import get_conn

PRICE_COLUMNS = ["code", "date", "open", "high", "low", "close", "adj_close", "volume"]


def upsert_price_daily(df: pd.DataFrame, *, source: str) -> int:
    """DataFrame を price_daily にUPSERT。返り値は反映行数."""
    if df.empty:
        return 0
    payload = df.copy()
    payload["source"] = source
    cols = [*PRICE_COLUMNS, "source"]
    with get_conn() as conn:
        conn.register("incoming_prices", payload[cols])
        conn.execute(
            "INSERT INTO price_daily(code, date, open, high, low, close, adj_close, volume, source) "
            "SELECT code, date, open, high, low, close, adj_close, volume, source FROM incoming_prices "
            "ON CONFLICT(code, date) DO UPDATE SET "
            "  open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close,"
            "  adj_close=excluded.adj_close, volume=excluded.volume, source=excluded.source"
        )
        conn.unregister("incoming_prices")
    return len(payload)


def update_codes(
    source: PriceSource,
    codes: list[str],
    start: date,
    end: date,
) -> dict[str, int]:
    """銘柄リストを一括更新."""
    summary: dict[str, int] = {}
    for code in codes:
        df = source.fetch_daily(code, start, end)
        n = upsert_price_daily(df, source=source.name)
        summary[code] = n
    return summary
