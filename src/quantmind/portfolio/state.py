"""保有銘柄ステート管理 (positions テーブル CRUD)."""

from __future__ import annotations

import uuid
import warnings
from dataclasses import dataclass
from datetime import date

from quantmind.storage import get_conn

MAX_POSITIONS = 5


@dataclass(frozen=True)
class Position:
    id: str
    code: str
    qty: int
    entry_price: float
    entry_date: date
    target_price: float | None
    stop_price: float | None
    scenario_id: str | None
    status: str
    exit_price: float | None
    exit_date: date | None
    realized_pnl: float | None


def _row_to_position(row: tuple) -> Position:
    return Position(
        id=row[0],
        code=row[1],
        qty=row[2],
        entry_price=row[3],
        entry_date=row[4],
        target_price=row[5],
        stop_price=row[6],
        scenario_id=row[7],
        status=row[8],
        exit_price=row[9],
        exit_date=row[10],
        realized_pnl=row[11],
    )


_SELECT = (
    "SELECT id, code, qty, entry_price, entry_date, target_price, stop_price, "
    "scenario_id, status, exit_price, exit_date, realized_pnl FROM positions"
)


def open_position(
    code: str,
    qty: int,
    entry_price: float,
    *,
    entry_date: date | None = None,
    target_price: float | None = None,
    stop_price: float | None = None,
    scenario_id: str | None = None,
    notes: str | None = None,
    position_id: str | None = None,
) -> Position:
    """新規エントリーを記録."""
    pid = position_id or str(uuid.uuid4())
    edate = entry_date or date.today()

    open_codes = [p.code for p in list_open()]
    if code in open_codes:
        warnings.warn(f"{code}: 既に保有中のため新規追加扱い (累積管理は未対応)", stacklevel=2)
    if len(open_codes) >= MAX_POSITIONS:
        warnings.warn(
            f"最大同時保有数 {MAX_POSITIONS} に達しています（現在 {len(open_codes)}）",
            stacklevel=2,
        )

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO positions(id, code, qty, entry_price, entry_date, target_price, stop_price, "
            "scenario_id, status, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)",
            [pid, code, qty, entry_price, edate, target_price, stop_price, scenario_id, notes],
        )
        row = conn.execute(_SELECT + " WHERE id=?", [pid]).fetchone()
    assert row is not None
    return _row_to_position(row)


def close_position(
    position_id: str,
    exit_price: float,
    *,
    exit_date: date | None = None,
) -> Position:
    """保有ポジションをクローズして実現損益を計算."""
    xdate = exit_date or date.today()
    with get_conn() as conn:
        cur = conn.execute(_SELECT + " WHERE id=?", [position_id]).fetchone()
        if cur is None:
            raise ValueError(f"position not found: {position_id}")
        pos = _row_to_position(cur)
        if pos.status != "open":
            raise ValueError(f"position {position_id} is already {pos.status}")
        pnl = (exit_price - pos.entry_price) * pos.qty
        conn.execute(
            "UPDATE positions SET status='closed', exit_price=?, exit_date=?, realized_pnl=? WHERE id=?",
            [exit_price, xdate, pnl, position_id],
        )
        row = conn.execute(_SELECT + " WHERE id=?", [position_id]).fetchone()
    assert row is not None
    return _row_to_position(row)


def list_open() -> list[Position]:
    with get_conn(read_only=True) as conn:
        rows = conn.execute(_SELECT + " WHERE status='open' ORDER BY entry_date").fetchall()
    return [_row_to_position(r) for r in rows]


def list_closed() -> list[Position]:
    with get_conn(read_only=True) as conn:
        rows = conn.execute(_SELECT + " WHERE status='closed' ORDER BY exit_date").fetchall()
    return [_row_to_position(r) for r in rows]


def portfolio_summary(price_lookup: dict[str, float] | None = None) -> dict[str, float]:
    """評価損益サマリを返す.

    Parameters
    ----------
    price_lookup : dict[str, float] | None
        ``code → 現在値`` のマップ。指定された銘柄のみ評価損益を加算。
    """
    open_pos = list_open()
    closed = list_closed()
    realized = sum((p.realized_pnl or 0.0) for p in closed)
    invested = sum(p.qty * p.entry_price for p in open_pos)
    unrealized = 0.0
    if price_lookup:
        for p in open_pos:
            if p.code in price_lookup:
                unrealized += (price_lookup[p.code] - p.entry_price) * p.qty
    return {
        "open_count": float(len(open_pos)),
        "closed_count": float(len(closed)),
        "invested_cost": float(invested),
        "unrealized_pnl": float(unrealized),
        "realized_pnl": float(realized),
    }
