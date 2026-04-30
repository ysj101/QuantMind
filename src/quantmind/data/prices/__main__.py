"""``python -m quantmind.data.prices update --codes ...`` CLI."""

from __future__ import annotations

import argparse
from datetime import date, timedelta

from quantmind.data.prices.ingest import update_codes
from quantmind.data.prices.yfinance_source import YFinanceSource


def _parse_date(s: str | None, default: date) -> date:
    if s is None:
        return default
    return date.fromisoformat(s)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quantmind.data.prices")
    sub = parser.add_subparsers(dest="cmd", required=True)
    upd = sub.add_parser("update", help="株価を取得して DB に反映")
    upd.add_argument("--codes", nargs="+", required=True, help="銘柄コード（例: 7203 6758）")
    upd.add_argument("--start", help="開始日 YYYY-MM-DD（既定: 1年前）")
    upd.add_argument("--end", help="終了日 YYYY-MM-DD（既定: 本日）")
    upd.add_argument("--source", default="yfinance", choices=["yfinance"])

    args = parser.parse_args(argv)
    end = _parse_date(args.end, date.today())
    start = _parse_date(args.start, end - timedelta(days=365))

    src = YFinanceSource()
    summary = update_codes(src, args.codes, start, end)
    for code, n in summary.items():
        print(f"{code}: {n} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
