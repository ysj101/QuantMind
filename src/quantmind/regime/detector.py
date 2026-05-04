"""VIX / 日経平均25日線 / 円ドル から Risk On/Off を判定."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from quantmind.storage import get_conn


@dataclass(frozen=True)
class RegimeConfig:
    vix_high: float = 25.0          # この値超で risk_off 寄り
    vix_extreme: float = 35.0       # 暴落シグナル
    n225_below_ma25_pct: float = -3.0  # 25日線比 -3% 以下を弱気とする
    usdjpy_change_5d_pct: float = -3.0  # 5日変化が -3% 以下（円急騰）= Risk Off
    risk_off_score_threshold: float = 0.5  # 0..1。これ以上で risk_off


DEFAULT_CONFIG = RegimeConfig()


@dataclass
class RegimeResult:
    as_of: date
    regime: str  # risk_on / risk_off / neutral
    score: float  # 0..1（高いほど risk_off 寄り）
    components: dict[str, Any] = field(default_factory=dict)


def _safe_pct_change(current: float, base: float) -> float:
    if base == 0:
        return 0.0
    return (current - base) / base * 100.0


def classify_regime(
    *,
    vix: float | None,
    n225_close: float | None,
    n225_ma25: float | None,
    usdjpy: float | None,
    usdjpy_5d_ago: float | None,
    as_of: date,
    config: RegimeConfig = DEFAULT_CONFIG,
) -> RegimeResult:
    """各指標から合成スコアを計算してレジーム判定."""
    components: dict[str, Any] = {}
    score = 0.0
    n_components = 0

    if vix is not None:
        components["vix"] = vix
        if vix >= config.vix_extreme:
            score += 1.0
        elif vix >= config.vix_high:
            score += 0.6
        else:
            score += 0.0
        n_components += 1

    if n225_close is not None and n225_ma25 is not None:
        diff = _safe_pct_change(n225_close, n225_ma25)
        components["n225_vs_ma25_pct"] = diff
        if diff <= config.n225_below_ma25_pct:
            score += 0.8
        elif diff < 0:
            score += 0.3
        else:
            score += 0.0
        n_components += 1

    if usdjpy is not None and usdjpy_5d_ago is not None:
        change = _safe_pct_change(usdjpy, usdjpy_5d_ago)
        components["usdjpy_change_5d_pct"] = change
        if change <= config.usdjpy_change_5d_pct:
            score += 0.6
        elif change < 0:
            score += 0.2
        else:
            score += 0.0
        n_components += 1

    normalized = score / n_components if n_components > 0 else 0.0
    if normalized >= config.risk_off_score_threshold:
        regime = "risk_off"
    elif normalized < 0.2:
        regime = "risk_on"
    else:
        regime = "neutral"
    return RegimeResult(as_of=as_of, regime=regime, score=normalized, components=components)


def load_config(path: Path) -> RegimeConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return RegimeConfig(**raw)


def save_regime(result: RegimeResult) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO macro_regime_daily(date, regime, score, components) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(date) DO UPDATE SET "
            "regime=excluded.regime, score=excluded.score, components=excluded.components",
            [result.as_of, result.regime, result.score, json.dumps(result.components)],
        )


def load_regime(as_of: date) -> RegimeResult | None:
    """保存済みレジーム判定を読み戻す."""
    with get_conn(read_only=True) as conn:
        row = conn.execute(
            "SELECT regime, score, components FROM macro_regime_daily WHERE date=?",
            [as_of],
        ).fetchone()
    if row is None:
        return None
    components_raw = row[2] or "{}"
    components = json.loads(components_raw) if isinstance(components_raw, str) else components_raw
    return RegimeResult(
        as_of=as_of,
        regime=str(row[0]),
        score=float(row[1] or 0.0),
        components=dict(components or {}),
    )
