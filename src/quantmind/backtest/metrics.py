"""バックテスト評価指標."""

from __future__ import annotations

import math
from collections.abc import Sequence


def sharpe_ratio(
    returns: Sequence[float],
    *,
    annualization_factor: int = 252,
    risk_free_rate: float = 0.0,
) -> float:
    """日次リターン列から年率シャープレシオを計算."""
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    excess = mean - risk_free_rate / annualization_factor
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    return excess / std * math.sqrt(annualization_factor)


def max_drawdown(equity_curve: Sequence[float]) -> float:
    """資産曲線から最大ドローダウン（負の値）を返す."""
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    mdd = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak <= 0:
            continue
        dd = (value / peak) - 1.0
        mdd = min(mdd, dd)
    return mdd


def profit_factor(trade_pnls: Sequence[float]) -> float:
    gains = sum(p for p in trade_pnls if p > 0)
    losses = -sum(p for p in trade_pnls if p < 0)
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def win_rate(trade_pnls: Sequence[float]) -> float:
    if not trade_pnls:
        return 0.0
    return sum(1 for p in trade_pnls if p > 0) / len(trade_pnls)
