"""ルールベース事前スクリーニングテスト."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from quantmind.screening import save_screening, screen
from quantmind.storage import get_conn, init_db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTMIND_DATA_DIR", str(tmp_path))
    init_db()


def _seed_universe(codes: list[str], as_of: date) -> None:
    with get_conn() as conn:
        for c in codes:
            conn.execute(
                "INSERT INTO universe_snapshots(date, code, market_cap_jpy, last_close, included, reason) "
                "VALUES (?, ?, ?, ?, ?, 'ok')",
                [as_of, c, 10_000_000_000, 500.0, True],
            )


def _seed_prices(code: str, end: date, closes: list[float], volumes: list[int]) -> None:
    """end から遡って n 日分を投入."""
    with get_conn() as conn:
        for i, (close, vol) in enumerate(zip(closes, volumes, strict=True)):
            d = end - timedelta(days=len(closes) - 1 - i)
            conn.execute(
                "INSERT INTO price_daily(code, date, open, high, low, close, volume, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'fake') "
                "ON CONFLICT(code, date) DO UPDATE SET close=excluded.close, volume=excluded.volume",
                [code, d, close, close + 1, close - 1, close, vol],
            )


def test_screen_picks_volume_spike() -> None:
    as_of = date(2026, 4, 30)
    _seed_universe(["1000", "2000"], as_of)
    # code 1000: 平常出来高 10000、当日 30000 で急増
    _seed_prices(
        "1000",
        as_of,
        closes=[500.0] * 25,
        volumes=[10000] * 24 + [30000],
    )
    # code 2000: 静か（ヒットしない）
    _seed_prices(
        "2000",
        as_of,
        closes=[500.0] * 25,
        volumes=[10000] * 25,
    )
    res = screen(as_of, top_n=10)
    codes = [r.code for r in res]
    assert "1000" in codes
    assert "2000" not in codes
    r1 = next(r for r in res if r.code == "1000")
    assert "volume_spike" in r1.rules_hit


def test_screen_picks_tdnet_today() -> None:
    as_of = date(2026, 4, 30)
    _seed_universe(["3000"], as_of)
    _seed_prices("3000", as_of, closes=[500.0] * 25, volumes=[10000] * 25)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO disclosures(id, code, source, doc_type, title, disclosed_at, url) "
            "VALUES ('d1', '3000', 'tdnet', 'forecast_revision', 'X', ?, NULL)",
            [datetime(2026, 4, 30, 15, 0)],
        )
    res = screen(as_of)
    assert any(r.code == "3000" and "tdnet_today" in r.rules_hit for r in res)


def test_screen_picks_ma25_deviation() -> None:
    as_of = date(2026, 4, 30)
    _seed_universe(["4000"], as_of)
    closes = [500.0] * 24 + [600.0]  # 直近 +20% 乖離
    _seed_prices("4000", as_of, closes=closes, volumes=[10000] * 25)
    res = screen(as_of)
    assert any(r.code == "4000" and "ma25_deviation" in r.rules_hit for r in res)


def test_screen_picks_post_earnings_reaction() -> None:
    as_of = date(2026, 4, 30)
    _seed_universe(["5000"], as_of)
    closes = [500.0] * 20 + [500.0, 510.0, 530.0, 550.0, 580.0]  # 直近5日で +16%
    _seed_prices("5000", as_of, closes=closes, volumes=[10000] * 25)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO disclosures(id, code, source, doc_type, title, disclosed_at, url) "
            "VALUES ('e1', '5000', 'tdnet', 'earnings', 'short shinpo', ?, NULL)",
            [datetime(2026, 4, 28, 15, 0)],
        )
    res = screen(as_of)
    assert any(r.code == "5000" and "post_earnings" in r.rules_hit for r in res)


def test_top_n_truncates() -> None:
    as_of = date(2026, 4, 30)
    codes = [f"{1000 + i:04d}" for i in range(15)]
    _seed_universe(codes, as_of)
    for i, c in enumerate(codes):
        # i 大きいほどボラ大きく → スコア高
        spike = 30000 + i * 1000
        _seed_prices(c, as_of, closes=[500.0] * 25, volumes=[10000] * 24 + [spike])
    res = screen(as_of, top_n=5)
    assert len(res) == 5
    # スコア降順
    assert res == sorted(res, key=lambda r: r.score, reverse=True)


def test_save_screening_persists_rules_hit() -> None:
    as_of = date(2026, 4, 30)
    _seed_universe(["1000"], as_of)
    _seed_prices("1000", as_of, closes=[500.0] * 25, volumes=[10000] * 24 + [30000])
    res = screen(as_of)
    save_screening(as_of, res)
    save_screening(as_of, res)  # 冪等
    with get_conn(read_only=True) as conn:
        rows = conn.execute(
            "SELECT code, rules_hit FROM screening_daily WHERE date=?", [as_of]
        ).fetchall()
    assert len(rows) == 1
    parsed = json.loads(rows[0][1])
    assert "volume_spike" in parsed
