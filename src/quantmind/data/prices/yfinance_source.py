"""yfinance 経由の PriceSource 実装.

東証コードは yfinance では ``<code>.T`` 形式で渡す必要がある。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential


class YFinanceSource:
    """yfinance を使った無料株価ソース."""

    name = "yfinance"

    def __init__(self, suffix: str = ".T") -> None:
        self.suffix = suffix

    def _ticker(self, code: str) -> str:
        if code.endswith(self.suffix):
            return code
        return f"{code}{self.suffix}"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    def _download(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        import yfinance as yf  # 遅延 import: extras なしでもパッケージ全体は import 可能

        df: Any = yf.download(
            ticker,
            start=start.isoformat(),
            end=end.isoformat(),
            auto_adjust=False,
            progress=False,
            threads=False,
        )
        return df

    def fetch_daily(self, code: str, start: date, end: date) -> pd.DataFrame:
        ticker = self._ticker(code)
        raw = self._download(ticker, start, end)
        if raw is None or raw.empty:
            return pd.DataFrame(
                columns=["code", "date", "open", "high", "low", "close", "adj_close", "volume"]
            )

        # MultiIndex 列を平坦化
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = [c[0] for c in raw.columns]

        df = raw.reset_index().rename(
            columns={
                "Date": "date",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Adj Close": "adj_close",
                "Volume": "volume",
            }
        )
        df["code"] = code.replace(self.suffix, "")
        df["date"] = pd.to_datetime(df["date"]).dt.date
        # 異常値除外: OHLC が NaN または 0 以下
        df = df.dropna(subset=["open", "high", "low", "close"])
        df = df[(df["close"] > 0) & (df["volume"] >= 0)]
        df["volume"] = df["volume"].astype("int64")
        return df[["code", "date", "open", "high", "low", "close", "adj_close", "volume"]].sort_values(
            "date"
        ).reset_index(drop=True)
