"""IR PDF 収集 CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

from quantmind.data.ir_docs.collector import IrDocsCollector, upsert_ir_documents
from quantmind.data.ir_docs.registry import IrPageRegistry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quantmind.data.ir_docs")
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect", help="IR ページから決算説明資料PDFを収集")
    c.add_argument("--registry", required=True, help="レジストリ YAML パス")
    c.add_argument("--codes", nargs="*", help="対象銘柄コード（省略時は全件）")

    args = parser.parse_args(argv)
    registry = IrPageRegistry.from_yaml(Path(args.registry))
    collector = IrDocsCollector(registry)
    results = collector.collect_for_codes(args.codes)
    n = upsert_ir_documents(results)
    print(f"collected {len(results)} entries; upserted {n} rows")
    for r in results:
        print(f"  {r.code}: status={r.extraction_status} url={r.pdf_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
