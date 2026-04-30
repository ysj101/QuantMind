"""EDINET CLI: list / download / extract."""

from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

from quantmind.data.edinet.client import EdinetClient
from quantmind.data.edinet.financials import (
    extract_financials_from_xbrl,
    upsert_financials,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quantmind.data.edinet")
    sub = parser.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list", help="指定日の提出書類を一覧")
    ls.add_argument("--date", required=True)

    dl = sub.add_parser("download", help="書類本体DL")
    dl.add_argument("doc_id")
    dl.add_argument("--kind", choices=["xbrl", "pdf"], default="xbrl")
    dl.add_argument("--out", default="./.cache/edinet")

    ex = sub.add_parser("extract-financials", help="ローカルXBRLから財務指標抽出")
    ex.add_argument("path")
    ex.add_argument("--code", required=True)
    ex.add_argument("--period", required=True)

    args = parser.parse_args(argv)
    api_key = os.environ.get("EDINET_API_KEY")
    if args.cmd == "list":
        client = EdinetClient(api_key=api_key)
        for d in client.list_documents(date.fromisoformat(args.date)):
            print(f"{d.doc_id}\t{d.code or '----'}\t{d.doc_type_code}\t{d.doc_description}")
    elif args.cmd == "download":
        client = EdinetClient(api_key=api_key)
        path = client.download(args.doc_id, kind=args.kind, out_dir=Path(args.out))
        print(f"saved {path}")
    elif args.cmd == "extract-financials":
        values = extract_financials_from_xbrl(Path(args.path))
        upsert_financials(args.code, args.period, values)
        print(values)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
