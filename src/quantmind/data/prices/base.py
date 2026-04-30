"""株価ソース抽象インタフェース."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

import pandas as pd


@dataclass(frozen=True)
class PriceBar:
    """日足1本分."""

    code: str
    date: date
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: int


class PriceSource(Protocol):
    """株価ヒストリカル取得の抽象."""

    name: str

    def fetch_daily(self, code: str, start: date, end: date) -> pd.DataFrame:
        """日足を取得して DataFrame で返す.

        Returns
        -------
        pandas.DataFrame
            列: code, date, open, high, low, close, adj_close, volume
            欠損日は除外、date は昇順、date は ``datetime.date`` 型または日付互換。
        """
        ...
