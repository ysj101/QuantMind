"""バックテスト CLI."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from quantmind.backtest.engine import run_backtest
from quantmind.backtest.report import generate_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quantmind.backtest")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--out", default="reports/backtest.html")
    args = parser.parse_args(argv)

    result = run_backtest(date.fromisoformat(args.start), date.fromisoformat(args.end))
    print(f"Sharpe: {result.sharpe:.3f}")
    print(f"MaxDD : {result.max_drawdown:.2%}")
    print(f"Trades: {result.n_trades}")
    out = generate_report(result, Path(args.out))
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
