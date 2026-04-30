"""``python -m quantmind.data.tdnet fetch --date YYYY-MM-DD`` CLI."""

from __future__ import annotations

import argparse
from datetime import date

from quantmind.data.tdnet.client import TdnetClient
from quantmind.data.tdnet.ingest import ingest_entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quantmind.data.tdnet")
    sub = parser.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="指定日のTDnet開示を収集")
    f.add_argument("--date", required=True, help="YYYY-MM-DD")
    args = parser.parse_args(argv)

    target = date.fromisoformat(args.date)
    client = TdnetClient()
    entries = client.list_for_date(target)
    n = ingest_entries(entries)
    print(f"fetched {len(entries)} entries; inserted {n} new")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
