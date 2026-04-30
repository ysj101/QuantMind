"""スクリーニング CLI."""

from __future__ import annotations

import argparse
from datetime import date

from quantmind.screening.rule_screener import save_screening, screen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quantmind.screening")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="Top N スクリーニング")
    r.add_argument("--date", required=True)
    r.add_argument("--top", type=int, default=10)

    args = parser.parse_args(argv)
    results = screen(date.fromisoformat(args.date), top_n=args.top)
    save_screening(date.fromisoformat(args.date), results)
    for rank, item in enumerate(results, start=1):
        print(f"{rank:>2} {item.code} score={item.score:.2f} rules={item.rules_hit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
