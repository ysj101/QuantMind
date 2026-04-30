"""portfolio.state テスト."""

from __future__ import annotations

import warnings
from datetime import date
from pathlib import Path

import pytest

from quantmind.portfolio import (
    close_position,
    list_open,
    open_position,
    portfolio_summary,
)
from quantmind.storage import init_db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTMIND_DATA_DIR", str(tmp_path))
    init_db()


def test_open_close_pnl() -> None:
    p = open_position("1234", 100, 500.0, entry_date=date(2026, 4, 1), scenario_id="scn-1")
    assert p.status == "open"
    closed = close_position(p.id, 600.0, exit_date=date(2026, 4, 5))
    assert closed.status == "closed"
    assert closed.realized_pnl == pytest.approx(10000.0)


def test_max_positions_warn() -> None:
    for i in range(5):
        open_position(f"100{i}", 100, 500.0)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        open_position("9999", 100, 500.0)  # 6個目で警告
        assert any("最大同時保有数" in str(x.message) for x in w)
    assert len(list_open()) == 6  # 拒否はせず通知のみ


def test_summary_with_price_lookup() -> None:
    p = open_position("1234", 100, 500.0)
    open_position("5678", 100, 300.0)
    summary = portfolio_summary(price_lookup={"1234": 550.0, "5678": 250.0})
    # 1234: +50*100 = +5000, 5678: -50*100 = -5000 → 0
    assert summary["unrealized_pnl"] == pytest.approx(0.0)
    assert summary["open_count"] == 2.0
    assert summary["invested_cost"] == pytest.approx(80000.0)
    # close one
    close_position(p.id, 600.0)
    summary2 = portfolio_summary()
    assert summary2["realized_pnl"] == pytest.approx(10000.0)
    assert summary2["closed_count"] == 1.0


def test_close_unknown_raises() -> None:
    with pytest.raises(ValueError):
        close_position("non-existent-id", 100.0)
