"""ルールベース事前スクリーニング.

ユニバースから Top N 銘柄を抽出し、各ルールのヒット理由を保持する。
LLM 投入対象を絞るための前段。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from quantmind.storage import get_conn

DEFAULT_RULE_WEIGHTS: dict[str, float] = {
    "volume_spike": 1.0,    # 出来高急増
    "tdnet_today": 0.8,     # 当日TDnet開示あり
    "ma25_deviation": 0.7,  # 25日線乖離
    "post_earnings": 0.6,   # 直近決算後の価格反応
}

VOLUME_SPIKE_RATIO = 2.0  # 当日出来高 / 20日平均 >= 2.0
MA25_DEVIATION_PCT = 5.0  # |close/MA25-1| >= 5%
POST_EARNINGS_DAYS = 5     # 直近5営業日内に earnings 開示
EARNINGS_PRICE_REACTION_PCT = 5.0  # 反応 ±5%


@dataclass(frozen=True)
class ScreeningResult:
    code: str
    score: float
    rules_hit: list[str]


def _price_history(conn, code: str, end: date, lookback: int = 30) -> pd.DataFrame:
    rows = conn.execute(
        "SELECT date, close, volume FROM price_daily WHERE code=? AND date<=? "
        "ORDER BY date DESC LIMIT ?",
        [code, end, lookback],
    ).fetchall()
    if not rows:
        return pd.DataFrame(columns=["date", "close", "volume"])
    df = pd.DataFrame(rows, columns=["date", "close", "volume"])
    return df.sort_values("date").reset_index(drop=True)


def _has_volume_spike(prices: pd.DataFrame) -> bool:
    if len(prices) < 21:
        return False
    avg20 = prices["volume"].iloc[-21:-1].mean()
    if avg20 <= 0:
        return False
    return bool(prices["volume"].iloc[-1] >= avg20 * VOLUME_SPIKE_RATIO)


def _has_tdnet_today(conn, code: str, as_of: date) -> bool:
    row = conn.execute(
        "SELECT 1 FROM disclosures WHERE code=? AND CAST(disclosed_at AS DATE)=? LIMIT 1",
        [code, as_of],
    ).fetchone()
    return row is not None


def _has_ma25_deviation(prices: pd.DataFrame) -> bool:
    if len(prices) < 25:
        return False
    ma25 = prices["close"].iloc[-25:].mean()
    if ma25 == 0:
        return False
    deviation = abs(prices["close"].iloc[-1] / ma25 - 1.0) * 100.0
    return bool(deviation >= MA25_DEVIATION_PCT)


def _has_post_earnings_reaction(conn, code: str, prices: pd.DataFrame, as_of: date) -> bool:
    if len(prices) < 2:
        return False
    earliest = as_of - timedelta(days=POST_EARNINGS_DAYS)
    row = conn.execute(
        "SELECT 1 FROM disclosures WHERE code=? AND doc_type='earnings' "
        "AND CAST(disclosed_at AS DATE) BETWEEN ? AND ? LIMIT 1",
        [code, earliest, as_of],
    ).fetchone()
    if row is None:
        return False
    # 直近5営業日内で価格±5%反応
    closes = prices["close"].tail(POST_EARNINGS_DAYS + 1)
    if len(closes) < 2:
        return False
    change = abs(closes.iloc[-1] / closes.iloc[0] - 1.0) * 100.0
    return bool(change >= EARNINGS_PRICE_REACTION_PCT)


def screen(
    as_of: date,
    *,
    top_n: int = 10,
    weights: dict[str, float] | None = None,
) -> list[ScreeningResult]:
    """対象日のユニバース included=True からスコアリング Top N 抽出."""
    w = {**DEFAULT_RULE_WEIGHTS, **(weights or {})}
    out: list[ScreeningResult] = []
    with get_conn(read_only=True) as conn:
        codes = [
            row[0]
            for row in conn.execute(
                "SELECT code FROM universe_snapshots WHERE date=? AND included=TRUE",
                [as_of],
            ).fetchall()
        ]
        for code in codes:
            prices = _price_history(conn, code, as_of, lookback=30)
            rules_hit: list[str] = []
            score = 0.0
            if _has_volume_spike(prices):
                rules_hit.append("volume_spike")
                score += w["volume_spike"]
            if _has_tdnet_today(conn, code, as_of):
                rules_hit.append("tdnet_today")
                score += w["tdnet_today"]
            if _has_ma25_deviation(prices):
                rules_hit.append("ma25_deviation")
                score += w["ma25_deviation"]
            if _has_post_earnings_reaction(conn, code, prices, as_of):
                rules_hit.append("post_earnings")
                score += w["post_earnings"]
            if score > 0:
                out.append(ScreeningResult(code=code, score=score, rules_hit=rules_hit))

    out.sort(key=lambda r: r.score, reverse=True)
    return out[:top_n]


def save_screening(as_of: date, results: list[ScreeningResult]) -> int:
    n = 0
    with get_conn() as conn:
        conn.execute("DELETE FROM screening_daily WHERE date=?", [as_of])
        for rank, r in enumerate(results, start=1):
            conn.execute(
                "INSERT INTO screening_daily(date, code, score, rules_hit, rank) "
                "VALUES (?, ?, ?, ?, ?)",
                [as_of, r.code, r.score, json.dumps(r.rules_hit, ensure_ascii=False), rank],
            )
            n += 1
    return n
