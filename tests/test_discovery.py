"""小型株候補発見・データブートストラップのテスト."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from quantmind.storage import get_conn, init_db
from quantmind.universe.discovery import (
    StockCandidate,
    _candidate_from_quote,
    bootstrap_market_data,
    upsert_stocks_master,
)


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTMIND_DATA_DIR", str(tmp_path))
    init_db()


class FakePriceSource:
    name = "fake"

    def fetch_daily(self, code: str, start: date, end: date) -> pd.DataFrame:
        rows = []
        for i in range(3):
            d = start + timedelta(days=i)
            rows.append(
                {
                    "code": code,
                    "date": d,
                    "open": 99.0,
                    "high": 101.0,
                    "low": 98.0,
                    "close": 100.0,
                    "adj_close": 100.0,
                    "volume": 10000 + i,
                }
            )
        return pd.DataFrame(rows)


def test_candidate_from_yfinance_quote() -> None:
    candidate = _candidate_from_quote(
        {
            "symbol": "8918.T",
            "shortName": "LAND CO LTD",
            "exchange": "JPX",
            "marketCap": 15_000_000_000,
            "regularMarketPrice": 10.0,
        }
    )

    assert candidate == StockCandidate(
        code="8918",
        name="LAND CO LTD",
        market="jpx",
        market_cap_jpy=15_000_000_000,
        price_jpy=10.0,
    )


def test_upsert_stocks_master() -> None:
    n = upsert_stocks_master(
        [StockCandidate("8918", "LAND CO LTD", "jpx", 15_000_000_000, 10.0)]
    )

    assert n == 1
    with get_conn(read_only=True) as conn:
        row = conn.execute(
            "SELECT code, name, market, market_cap_jpy FROM stocks_master WHERE code='8918'"
        ).fetchone()
    assert row == ("8918", "LAND CO LTD", "jpx", 15_000_000_000)


def test_bootstrap_market_data_updates_master_and_prices() -> None:
    result = bootstrap_market_data(
        date(2026, 5, 5),
        candidates=[StockCandidate("8918", "LAND CO LTD", "jpx", 15_000_000_000, 10.0)],
        price_source=FakePriceSource(),
    )

    assert [c.code for c in result.candidates] == ["8918"]
    assert result.price_rows_by_code == {"8918": 3}
    with get_conn(read_only=True) as conn:
        n_master = conn.execute("SELECT COUNT(*) FROM stocks_master").fetchone()
        n_prices = conn.execute("SELECT COUNT(*) FROM price_daily WHERE code='8918'").fetchone()
    assert n_master == (1,)
    assert n_prices == (3,)
