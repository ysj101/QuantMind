"""TdnetEntry を disclosures テーブルへ冪等投入."""

from __future__ import annotations

import json
from collections.abc import Iterable

from quantmind.data.tdnet.classifier import classify_title
from quantmind.data.tdnet.client import TdnetEntry
from quantmind.storage import get_conn


def ingest_entries(entries: Iterable[TdnetEntry]) -> int:
    """既存IDをスキップして新規のみ INSERT。挿入件数を返す."""
    inserted = 0
    with get_conn() as conn:
        for e in entries:
            existing = conn.execute(
                "SELECT 1 FROM disclosures WHERE id=?", [e.raw_id]
            ).fetchone()
            if existing is not None:
                continue
            doc_type = classify_title(e.title)
            conn.execute(
                "INSERT INTO disclosures(id, code, source, doc_type, title, disclosed_at, url, raw_json) "
                "VALUES (?, ?, 'tdnet', ?, ?, ?, ?, ?)",
                [
                    e.raw_id,
                    e.code,
                    doc_type,
                    e.title,
                    e.disclosed_at,
                    e.pdf_url,
                    json.dumps(
                        {"name": e.name, "raw_id": e.raw_id},
                        ensure_ascii=False,
                    ),
                ],
            )
            inserted += 1
    return inserted
