"""ユニバース構築 CLI."""

from __future__ import annotations

import argparse
from datetime import date

from quantmind.universe.builder import (
    UniverseConfig,
    build_universe,
    save_universe_snapshot,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quantmind.universe")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="ユニバース構築・保存")
    b.add_argument("--date", required=True)
    b.add_argument("--mcap-cap", type=int, default=50_000_000_000)
    b.add_argument("--price-max", type=float, default=670.0)
    b.add_argument("--no-price-filter", action="store_true")
    b.add_argument("--exclude-market", nargs="*", default=[])

    args = parser.parse_args(argv)
    cfg = UniverseConfig(
        market_cap_cap_jpy=args.mcap_cap,
        price_max_jpy=None if args.no_price_filter else args.price_max,
        excluded_markets=tuple(args.exclude_market),
    )
    rows = build_universe(date.fromisoformat(args.date), config=cfg)
    n = save_universe_snapshot(date.fromisoformat(args.date), rows)
    included = sum(1 for r in rows if r.included)
    print(f"saved {n} rows; included={included}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
