"""ルールベース戦略の日次バックテスト.

LLM 部分は対象外。``screening_daily`` のスコア（または同等の信号）を
日次に再現してエントリー／クローズを実行する。
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from quantmind.backtest.metrics import (
    max_drawdown,
    profit_factor,
    sharpe_ratio,
    win_rate,
)
from quantmind.storage import get_conn

log = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    initial_cash: float = 200_000.0
    max_positions: int = 5
    take_profit_pct: float = 8.0      # +8% で利食い
    stop_loss_pct: float = -5.0       # -5% で損切り
    holding_days_max: int = 20         # 最大保有日数
    commission_pct: float = 0.05       # 0.05% 片道
    slippage_pct: float = 0.05         # 0.05%
    score_threshold: float = 1.5       # screening_daily.score >= でエントリー


@dataclass
class Trade:
    code: str
    entry_date: date
    entry_price: float
    exit_date: date
    exit_price: float
    qty: int
    pnl: float
    holding_days: int
    reason: str  # take_profit / stop_loss / time_exit


@dataclass
class BacktestResult:
    sharpe: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    avg_holding_days: float
    n_trades: int
    equity_curve: list[tuple[date, float]] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)


def _load_dates(conn, start: date, end: date) -> list[date]:
    rows = conn.execute(
        "SELECT DISTINCT date FROM price_daily WHERE date BETWEEN ? AND ? ORDER BY date",
        [start, end],
    ).fetchall()
    return [r[0] for r in rows]


def _load_signals(conn, start: date, end: date) -> dict[date, list[tuple[str, float]]]:
    rows = conn.execute(
        "SELECT date, code, score FROM screening_daily WHERE date BETWEEN ? AND ? ORDER BY date, rank",
        [start, end],
    ).fetchall()
    signals: dict[date, list[tuple[str, float]]] = {}
    for d, code, score in rows:
        signals.setdefault(d, []).append((code, float(score)))
    return signals


def _load_prices(conn, start: date, end: date) -> dict[tuple[date, str], float]:
    rows = conn.execute(
        "SELECT date, code, close FROM price_daily WHERE date BETWEEN ? AND ?",
        [start, end],
    ).fetchall()
    return {(r[0], r[1]): float(r[2]) for r in rows}


def run_backtest(
    start: date,
    end: date,
    *,
    config: BacktestConfig | None = None,
    persist: bool = True,
) -> BacktestResult:
    cfg = config or BacktestConfig()
    cash = cfg.initial_cash
    positions: dict[str, dict] = {}  # code -> {entry_date, entry_price, qty}
    trades: list[Trade] = []
    equity_curve: list[tuple[date, float]] = []

    with get_conn(read_only=True) as conn:
        dates = _load_dates(conn, start, end)
        signals = _load_signals(conn, start, end)
        prices = _load_prices(conn, start, end)

    for d in dates:
        # 1) ポジションのクローズ判定
        for code in list(positions.keys()):
            pos = positions[code]
            close_price = prices.get((d, code))
            if close_price is None:
                continue
            ret_pct = (close_price / pos["entry_price"] - 1) * 100.0
            holding = (d - pos["entry_date"]).days
            reason: str | None = None
            if ret_pct >= cfg.take_profit_pct:
                reason = "take_profit"
            elif ret_pct <= cfg.stop_loss_pct:
                reason = "stop_loss"
            elif holding >= cfg.holding_days_max:
                reason = "time_exit"
            if reason:
                exit_price = close_price * (1 - cfg.slippage_pct / 100)
                gross = (exit_price - pos["entry_price"]) * pos["qty"]
                commission = (
                    pos["entry_price"] * pos["qty"] * cfg.commission_pct / 100
                    + exit_price * pos["qty"] * cfg.commission_pct / 100
                )
                pnl = gross - commission
                cash += exit_price * pos["qty"] - commission / 2
                trades.append(
                    Trade(
                        code=code,
                        entry_date=pos["entry_date"],
                        entry_price=pos["entry_price"],
                        exit_date=d,
                        exit_price=exit_price,
                        qty=pos["qty"],
                        pnl=pnl,
                        holding_days=holding,
                        reason=reason,
                    )
                )
                del positions[code]

        # 2) エントリー判定（保有数の余裕がある時のみ）
        avail = cfg.max_positions - len(positions)
        if avail > 0 and d in signals:
            picks = sorted(signals[d], key=lambda kv: kv[1], reverse=True)
            slot_budget = cash / avail if avail > 0 else 0.0
            for code, score in picks:
                if avail <= 0:
                    break
                if score < cfg.score_threshold:
                    continue
                if code in positions:
                    continue
                close_price = prices.get((d, code))
                if close_price is None or close_price <= 0:
                    continue
                # 単元株 = 100株
                buy_price = close_price * (1 + cfg.slippage_pct / 100)
                qty = int(slot_budget // (buy_price * 100)) * 100
                if qty < 100:
                    continue
                cost = buy_price * qty * (1 + cfg.commission_pct / 100)
                if cost > cash:
                    continue
                cash -= cost
                positions[code] = {"entry_date": d, "entry_price": buy_price, "qty": qty}
                avail -= 1

        # 3) 日次評価額（保有時価評価 + cash）
        position_value = sum(
            prices.get((d, c), p["entry_price"]) * p["qty"] for c, p in positions.items()
        )
        equity_curve.append((d, cash + position_value))

    # 評価指標
    if len(equity_curve) >= 2:
        equity_values = [v for _, v in equity_curve]
        daily_returns = [
            (equity_values[i] / equity_values[i - 1]) - 1.0
            for i in range(1, len(equity_values))
            if equity_values[i - 1] > 0
        ]
    else:
        daily_returns = []
    pnls = [t.pnl for t in trades]
    avg_hold = sum(t.holding_days for t in trades) / len(trades) if trades else 0.0
    result = BacktestResult(
        sharpe=sharpe_ratio(daily_returns),
        max_drawdown=max_drawdown([v for _, v in equity_curve]),
        win_rate=win_rate(pnls),
        profit_factor=profit_factor(pnls),
        avg_holding_days=avg_hold,
        n_trades=len(trades),
        equity_curve=equity_curve,
        trades=trades,
    )

    if persist:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO backtest_runs(id, config, start_date, end_date, sharpe, max_drawdown, "
                "win_rate, profit_factor, avg_holding_days, equity_curve) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    str(uuid.uuid4()),
                    json.dumps(cfg.__dict__),
                    start,
                    end,
                    result.sharpe,
                    result.max_drawdown,
                    result.win_rate,
                    result.profit_factor,
                    result.avg_holding_days,
                    json.dumps(
                        [
                            {"date": d.isoformat(), "equity": v}
                            for d, v in equity_curve
                        ]
                    ),
                ],
            )
    return result


def equity_curve_to_dataframe(result: BacktestResult) -> pd.DataFrame:
    return pd.DataFrame(result.equity_curve, columns=["date", "equity"])
