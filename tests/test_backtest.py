"""バックテストエンジンテスト."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from quantmind.backtest import BacktestConfig, generate_report, run_backtest
from quantmind.backtest.metrics import (
    max_drawdown,
    profit_factor,
    sharpe_ratio,
    win_rate,
)
from quantmind.storage import get_conn, init_db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTMIND_DATA_DIR", str(tmp_path))
    init_db()


def test_metrics_basic() -> None:
    assert sharpe_ratio([0.001, 0.002, 0.003, 0.004]) > 0
    assert sharpe_ratio([]) == 0.0
    assert max_drawdown([100, 110, 90, 95, 80]) == pytest.approx((80 / 110) - 1)
    assert win_rate([1, -1, 2, -2, 3]) == pytest.approx(3 / 5)
    assert profit_factor([1, -1, 2]) == pytest.approx(3.0)


def _seed_market(start: date, end: date) -> None:
    """連続日付の価格・スクリーニングを投入. 銘柄1個・常時上昇."""
    with get_conn() as conn:
        d = start
        price = 100.0  # 単元株（100株）×40000円予算 で買える価格帯
        i = 0
        while d <= end:
            # 1日1%ずつ上昇
            close = price * (1.01**i)
            conn.execute(
                "INSERT INTO price_daily(code, date, open, high, low, close, volume, source) "
                "VALUES ('1234', ?, ?, ?, ?, ?, ?, 'fake')",
                [d, close - 1, close + 1, close - 2, close, 100000],
            )
            # 日次スクリーニングでシグナル発生
            conn.execute(
                "INSERT INTO screening_daily(date, code, score, rules_hit, rank) "
                "VALUES (?, '1234', 2.0, ?, 1)",
                [d, json.dumps(["volume_spike"])],
            )
            d += timedelta(days=1)
            i += 1


def test_run_backtest_takes_profit() -> None:
    start = date(2026, 1, 1)
    end = date(2026, 1, 31)
    _seed_market(start, end)
    cfg = BacktestConfig(
        initial_cash=200_000,
        take_profit_pct=8.0,
        stop_loss_pct=-5.0,
        holding_days_max=20,
        score_threshold=1.0,
    )
    result = run_backtest(start, end, config=cfg)
    assert result.n_trades >= 1
    assert any(t.reason == "take_profit" for t in result.trades)
    # シャープレシオは正
    assert result.sharpe > 0


def test_run_backtest_persists_to_db() -> None:
    start = date(2026, 1, 1)
    end = date(2026, 1, 31)
    _seed_market(start, end)
    run_backtest(start, end)
    with get_conn(read_only=True) as conn:
        rows = conn.execute("SELECT sharpe, max_drawdown FROM backtest_runs").fetchall()
    assert len(rows) == 1
    assert rows[0][0] is not None


def test_generate_report_writes_html(tmp_path: Path) -> None:
    start = date(2026, 1, 1)
    end = date(2026, 1, 10)
    _seed_market(start, end)
    result = run_backtest(start, end, persist=False)
    out = generate_report(result, tmp_path / "bt.html")
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    assert "シャープレシオ" in html
    assert "最大ドローダウン" in html


def test_no_signals_yields_no_trades() -> None:
    """スクリーニングなし → 取引ゼロ."""
    start = date(2026, 1, 1)
    end = date(2026, 1, 10)
    with get_conn() as conn:
        d = start
        while d <= end:
            conn.execute(
                "INSERT INTO price_daily(code, date, open, high, low, close, volume, source) "
                "VALUES ('1234', ?, 500, 510, 490, 500, 100000, 'fake')",
                [d],
            )
            d += timedelta(days=1)
    result = run_backtest(start, end, persist=False)
    assert result.n_trades == 0
