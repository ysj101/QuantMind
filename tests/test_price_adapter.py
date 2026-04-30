"""価格アダプタ抽象層の挙動確認."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from quantmind.data.prices import PriceSource, upsert_price_daily
from quantmind.data.prices.ingest import update_codes
from quantmind.storage import get_conn, init_db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTMIND_DATA_DIR", str(tmp_path))
    init_db()


class FakeSource:
    """テスト用 PriceSource 実装."""

    name = "fake"

    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames

    def fetch_daily(self, code: str, start: date, end: date) -> pd.DataFrame:
        return self._frames.get(code, pd.DataFrame()).copy()


def _bar(code: str, d: str, close: float = 100.0) -> dict[str, object]:
    return {
        "code": code,
        "date": date.fromisoformat(d),
        "open": close - 1.0,
        "high": close + 1.0,
        "low": close - 2.0,
        "close": close,
        "adj_close": close,
        "volume": 10000,
    }


def test_protocol_compatibility() -> None:
    src: PriceSource = FakeSource({})
    assert src.name == "fake"


def test_upsert_inserts_and_updates() -> None:
    df = pd.DataFrame([_bar("1234", "2026-04-01", 100.0), _bar("1234", "2026-04-02", 105.0)])
    n = upsert_price_daily(df, source="fake")
    assert n == 2

    # 同日を更新（close 違い）
    df2 = pd.DataFrame([_bar("1234", "2026-04-02", 110.0)])
    upsert_price_daily(df2, source="fake")
    with get_conn(read_only=True) as conn:
        rows = conn.execute(
            "SELECT date, close FROM price_daily WHERE code='1234' ORDER BY date"
        ).fetchall()
    assert len(rows) == 2
    assert rows[1][1] == 110.0


def test_update_codes_dispatches_per_code() -> None:
    frames = {
        "1234": pd.DataFrame([_bar("1234", "2026-04-01"), _bar("1234", "2026-04-02")]),
        "5678": pd.DataFrame([_bar("5678", "2026-04-01")]),
    }
    src = FakeSource(frames)
    summary = update_codes(src, ["1234", "5678"], date(2026, 4, 1), date(2026, 4, 2))
    assert summary == {"1234": 2, "5678": 1}


def test_yfinance_source_ticker_formatting() -> None:
    from quantmind.data.prices.yfinance_source import YFinanceSource

    src = YFinanceSource()
    assert src._ticker("7203") == "7203.T"
    assert src._ticker("7203.T") == "7203.T"


def test_yfinance_source_empty_returns_empty_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    """yfinance がデータ無しの場合でも空DFを返す."""
    from quantmind.data.prices import yfinance_source as ymod

    src = ymod.YFinanceSource()
    monkeypatch.setattr(src, "_download", lambda *a, **k: pd.DataFrame())
    out = src.fetch_daily("9999", date(2026, 4, 1), date(2026, 4, 2))
    assert out.empty
    assert list(out.columns) == [
        "code",
        "date",
        "open",
        "high",
        "low",
        "close",
        "adj_close",
        "volume",
    ]
