"""小型株ユニバース構築."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from quantmind.storage import get_conn

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class UniverseConfig:
    market_cap_cap_jpy: int = 50_000_000_000  # 500億円
    price_max_jpy: float | None = 670.0  # 単元株×20万円÷5銘柄想定
    excluded_markets: tuple[str, ...] = ()
    excluded_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class UniverseRow:
    code: str
    market_cap_jpy: int | None
    last_close: float | None
    included: bool
    reason: str


def _last_close(conn, code: str, as_of: date) -> float | None:
    row = conn.execute(
        "SELECT close FROM price_daily WHERE code=? AND date<=? ORDER BY date DESC LIMIT 1",
        [code, as_of],
    ).fetchone()
    return None if row is None else float(row[0])


def build_universe(
    as_of: date,
    *,
    config: UniverseConfig | None = None,
) -> list[UniverseRow]:
    """``stocks_master`` × 直近 ``price_daily`` から条件適合銘柄を抽出する.

    上場廃止／監理銘柄の除外は ``excluded_codes`` で行う（外部からリスト供給）。
    """
    cfg = config or UniverseConfig()
    out: list[UniverseRow] = []
    with get_conn(read_only=True) as conn:
        rows: Iterable[tuple] = conn.execute(
            "SELECT code, market, market_cap_jpy FROM stocks_master"
        ).fetchall()

        for code, market, mcap in rows:
            included = True
            reason_parts: list[str] = []

            if code in cfg.excluded_codes:
                included = False
                reason_parts.append("excluded_code")

            if market in cfg.excluded_markets:
                included = False
                reason_parts.append(f"excluded_market:{market}")

            if mcap is not None and mcap > cfg.market_cap_cap_jpy:
                included = False
                reason_parts.append("mcap_over")

            close = _last_close(conn, code, as_of)
            if cfg.price_max_jpy is not None and close is not None and close > cfg.price_max_jpy:
                included = False
                reason_parts.append("price_over")

            reason = ",".join(reason_parts) if reason_parts else "ok"
            out.append(
                UniverseRow(
                    code=code,
                    market_cap_jpy=mcap,
                    last_close=close,
                    included=included,
                    reason=reason,
                )
            )
    n_included = sum(1 for r in out if r.included)
    log.info("universe %s: total=%d included=%d", as_of, len(out), n_included)
    return out


def save_universe_snapshot(as_of: date, rows: list[UniverseRow]) -> int:
    n = 0
    with get_conn() as conn:
        # 同日既存を削除して再投入
        conn.execute("DELETE FROM universe_snapshots WHERE date=?", [as_of])
        for r in rows:
            conn.execute(
                "INSERT INTO universe_snapshots(date, code, market_cap_jpy, last_close, included, reason) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [as_of, r.code, r.market_cap_jpy, r.last_close, r.included, r.reason],
            )
            n += 1
    return n


def load_universe_snapshot(as_of: date) -> list[UniverseRow]:
    """保存済みユニバーススナップショットを読み戻す."""
    with get_conn(read_only=True) as conn:
        rows = conn.execute(
            "SELECT code, market_cap_jpy, last_close, included, reason "
            "FROM universe_snapshots WHERE date=? ORDER BY code",
            [as_of],
        ).fetchall()
    return [
        UniverseRow(
            code=str(code),
            market_cap_jpy=None if mcap is None else int(mcap),
            last_close=None if close is None else float(close),
            included=bool(included),
            reason=str(reason or ""),
        )
        for code, mcap, close, included, reason in rows
    ]
