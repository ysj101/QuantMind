"""ユニバース構築テスト."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from quantmind.storage import get_conn, init_db
from quantmind.universe import (
    UniverseConfig,
    build_universe,
    save_universe_snapshot,
)


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTMIND_DATA_DIR", str(tmp_path))
    init_db()
    # 銘柄マスタ + 直近終値を投入
    with get_conn() as conn:
        rows = [
            # (code, name, market, mcap_jpy)
            ("1000", "Small A", "growth", 30_000_000_000),  # 300億, 価格500 → ok
            ("2000", "Small B", "standard", 49_000_000_000),  # 490億, 価格700 → 価格超
            ("3000", "Mid", "prime", 80_000_000_000),         # 800億 → mcap超
            ("4000", "Cheap Big", "prime", 200_000_000_000),  # 2000億 → mcap超
            ("5000", "Tiny growth", "growth", 5_000_000_000),  # 50億, 価格200 → ok
        ]
        for code, name, market, mcap in rows:
            conn.execute(
                "INSERT INTO stocks_master(code, name, market, market_cap_jpy) VALUES (?, ?, ?, ?)",
                [code, name, market, mcap],
            )
        prices = [("1000", 500.0), ("2000", 700.0), ("3000", 1500.0), ("4000", 800.0), ("5000", 200.0)]
        for code, close in prices:
            conn.execute(
                "INSERT INTO price_daily(code, date, open, high, low, close, volume, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'fake')",
                [code, date(2026, 4, 30), close - 5, close + 5, close - 10, close, 100000],
            )


def test_default_config_filters_correctly() -> None:
    rows = build_universe(date(2026, 4, 30))
    by_code = {r.code: r for r in rows}
    assert by_code["1000"].included is True
    assert by_code["2000"].included is False  # 価格700>670
    assert by_code["3000"].included is False  # mcap 800億
    assert by_code["4000"].included is False  # mcap 2000億
    assert by_code["5000"].included is True


def test_no_price_filter_lets_price_pass() -> None:
    rows = build_universe(
        date(2026, 4, 30),
        config=UniverseConfig(market_cap_cap_jpy=50_000_000_000, price_max_jpy=None),
    )
    by_code = {r.code: r for r in rows}
    assert by_code["2000"].included is True  # 価格制約なし、490億で通る


def test_excluded_market_filters_out_prime() -> None:
    rows = build_universe(
        date(2026, 4, 30),
        config=UniverseConfig(
            market_cap_cap_jpy=300_000_000_000,
            price_max_jpy=None,
            excluded_markets=("prime",),
        ),
    )
    by_code = {r.code: r for r in rows}
    assert by_code["3000"].included is False
    assert "excluded_market:prime" in by_code["3000"].reason


def test_save_universe_snapshot_replaces_same_day() -> None:
    rows = build_universe(date(2026, 4, 30))
    n1 = save_universe_snapshot(date(2026, 4, 30), rows)
    n2 = save_universe_snapshot(date(2026, 4, 30), rows)
    assert n1 == n2
    with get_conn(read_only=True) as conn:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM universe_snapshots WHERE date='2026-04-30'"
        ).fetchone()
    assert cnt is not None
    assert cnt[0] == n1


def test_universe_size_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    with caplog.at_level(logging.INFO):
        build_universe(date(2026, 4, 30))
    assert any("universe" in rec.message and "included" in rec.message for rec in caplog.records)
