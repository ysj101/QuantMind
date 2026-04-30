"""マクロレジーム判定テスト."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from quantmind.regime import classify_regime, save_regime
from quantmind.regime.detector import DEFAULT_CONFIG, load_config
from quantmind.storage import get_conn, init_db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTMIND_DATA_DIR", str(tmp_path))
    init_db()


def test_calm_market_is_risk_on() -> None:
    result = classify_regime(
        vix=14.0,
        n225_close=39000.0,
        n225_ma25=38500.0,  # +1.3%
        usdjpy=150.0,
        usdjpy_5d_ago=149.5,  # +0.3%
        as_of=date(2026, 4, 30),
    )
    assert result.regime == "risk_on"
    assert result.score < 0.2


def test_corona_shock_is_risk_off() -> None:
    """2020-03 コロナショック相当: VIX 80, 日経 -20%, 円急騰."""
    result = classify_regime(
        vix=80.0,
        n225_close=17000.0,
        n225_ma25=21000.0,  # -19%
        usdjpy=102.0,
        usdjpy_5d_ago=110.0,  # -7.3%
        as_of=date(2020, 3, 16),
    )
    assert result.regime == "risk_off"
    assert result.score >= 0.5
    assert "vix" in result.components
    assert result.components["vix"] == 80.0


def test_neutral_zone() -> None:
    result = classify_regime(
        vix=27.0,  # 25..35 → 0.6
        n225_close=38000.0,
        n225_ma25=38500.0,  # -1.3% → 0.3
        usdjpy=150.0,
        usdjpy_5d_ago=151.0,  # -0.66% → 0.2
        as_of=date(2026, 4, 30),
    )
    # 平均 = (0.6+0.3+0.2)/3 ≒ 0.366 → neutral
    assert result.regime == "neutral"
    assert 0.2 <= result.score < 0.5


def test_partial_data_still_works() -> None:
    result = classify_regime(
        vix=18.0,
        n225_close=None,
        n225_ma25=None,
        usdjpy=None,
        usdjpy_5d_ago=None,
        as_of=date(2026, 4, 30),
    )
    assert result.regime == "risk_on"  # VIX 18 → score 0


def test_config_yaml_load(tmp_path: Path) -> None:
    p = tmp_path / "c.yaml"
    p.write_text(
        "vix_high: 20.0\nvix_extreme: 30.0\nrisk_off_score_threshold: 0.4\n", encoding="utf-8"
    )
    cfg = load_config(p)
    assert cfg.vix_high == 20.0
    assert cfg.vix_extreme == 30.0
    assert cfg.risk_off_score_threshold == 0.4
    # 未指定はデフォルト
    assert cfg.n225_below_ma25_pct == DEFAULT_CONFIG.n225_below_ma25_pct


def test_save_regime_roundtrip() -> None:
    result = classify_regime(
        vix=14.0,
        n225_close=39000.0,
        n225_ma25=38500.0,
        usdjpy=150.0,
        usdjpy_5d_ago=149.5,
        as_of=date(2026, 4, 30),
    )
    save_regime(result)
    save_regime(result)  # 冪等
    with get_conn(read_only=True) as conn:
        rows = conn.execute(
            "SELECT regime FROM macro_regime_daily WHERE date='2026-04-30'"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "risk_on"
