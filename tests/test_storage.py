"""storage モジュール基本CRUDテスト."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from quantmind.storage import get_conn, init_db, read_parquet, write_parquet


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("QUANTMIND_DATA_DIR", str(tmp_path))
    return tmp_path


def test_init_db_creates_file(isolated_data_dir: Path) -> None:
    path = init_db()
    assert path.exists()


def test_all_tables_created() -> None:
    init_db()
    expected = {
        "stocks_master",
        "price_daily",
        "disclosures",
        "financials",
        "officers",
        "ir_documents",
        "llm_decisions",
        "falsifiability_scenarios",
        "positions",
        "postmortems",
        "macro_regime_daily",
        "universe_snapshots",
        "screening_daily",
        "pipeline_runs",
        "alerts",
        "backtest_runs",
    }
    with get_conn(read_only=True) as conn:
        rows = conn.execute("SELECT table_name FROM information_schema.tables").fetchall()
    actual = {r[0] for r in rows}
    missing = expected - actual
    assert not missing, f"missing tables: {missing}"


def test_basic_crud_each_table() -> None:
    init_db()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO stocks_master(code, name, market, market_cap_jpy) VALUES (?, ?, ?, ?)",
            ["1234", "テスト株式", "growth", 5_000_000_000],
        )
        row = conn.execute(
            "SELECT name, market_cap_jpy FROM stocks_master WHERE code=?", ["1234"]
        ).fetchone()
        assert row == ("テスト株式", 5_000_000_000)

        conn.execute(
            "INSERT INTO price_daily(code, date, open, high, low, close, volume, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ["1234", "2026-04-01", 100.0, 110.0, 95.0, 108.0, 100000, "yfinance"],
        )
        n = conn.execute("SELECT COUNT(*) FROM price_daily").fetchone()
        assert n is not None and n[0] == 1


def test_parquet_roundtrip(tmp_path: Path) -> None:
    df = pd.DataFrame({"code": ["1234", "5678"], "close": [100.0, 200.0]})
    p = write_parquet(df, tmp_path / "x.parquet")
    out = read_parquet(p)
    assert list(out["code"]) == ["1234", "5678"]


def test_init_idempotent() -> None:
    init_db()
    init_db()  # 二回目もエラーにならない
    with get_conn(read_only=True) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version='0001_initial'"
        ).fetchone()
        assert row is not None and row[0] == 1


def test_data_dir_uses_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "elsewhere"
    monkeypatch.setenv("QUANTMIND_DATA_DIR", str(target))
    from quantmind.storage import data_dir

    assert data_dir() == target
    assert target.exists()
    # cleanup the env to not leak
    os.environ.pop("QUANTMIND_DATA_DIR", None)
