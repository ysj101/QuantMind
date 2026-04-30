"""ポジション CLI: open / close / list."""

from __future__ import annotations

import argparse
from datetime import date

from quantmind.portfolio.state import (
    close_position,
    list_closed,
    list_open,
    open_position,
    portfolio_summary,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quantmind.portfolio")
    sub = parser.add_subparsers(dest="cmd", required=True)

    op = sub.add_parser("open", help="新規エントリー")
    op.add_argument("code")
    op.add_argument("qty", type=int)
    op.add_argument("price", type=float)
    op.add_argument("--target", type=float)
    op.add_argument("--stop", type=float)
    op.add_argument("--scenario", help="反証シナリオID")
    op.add_argument("--date", help="エントリー日 YYYY-MM-DD")

    cl = sub.add_parser("close", help="クローズ")
    cl.add_argument("position_id")
    cl.add_argument("price", type=float)
    cl.add_argument("--date", help="クローズ日 YYYY-MM-DD")

    sub.add_parser("list", help="現在保有を一覧")
    sub.add_parser("history", help="クローズ済みを一覧")
    sub.add_parser("summary", help="評価サマリ")

    args = parser.parse_args(argv)

    if args.cmd == "open":
        pos = open_position(
            args.code,
            args.qty,
            args.price,
            entry_date=date.fromisoformat(args.date) if args.date else None,
            target_price=args.target,
            stop_price=args.stop,
            scenario_id=args.scenario,
        )
        print(f"opened {pos.id}: {pos.code} x{pos.qty} @ {pos.entry_price}")
    elif args.cmd == "close":
        pos = close_position(
            args.position_id,
            args.price,
            exit_date=date.fromisoformat(args.date) if args.date else None,
        )
        print(f"closed {pos.id}: pnl={pos.realized_pnl}")
    elif args.cmd == "list":
        for p in list_open():
            print(f"{p.id} {p.code} qty={p.qty} entry={p.entry_price} target={p.target_price} stop={p.stop_price}")
    elif args.cmd == "history":
        for p in list_closed():
            print(f"{p.id} {p.code} entry={p.entry_price} exit={p.exit_price} pnl={p.realized_pnl}")
    elif args.cmd == "summary":
        s = portfolio_summary()
        for k, v in s.items():
            print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
