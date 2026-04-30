"""IR ページから決算説明資料 PDF を収集してテキスト化する."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from quantmind.data.ir_docs.registry import IrPageRegistry, RegistryEntry
from quantmind.storage import get_conn

log = logging.getLogger(__name__)

DEFAULT_KEYWORD = "決算説明"
PDF_LINK_RE = re.compile(r'<a[^>]*href="(?P<href>[^"]+\.pdf)"[^>]*>(?P<text>[^<]+)</a>', re.IGNORECASE)


@dataclass(frozen=True)
class IrDocsResult:
    code: str
    pdf_url: str | None
    extraction_status: str
    body_text: str | None
    error: str | None = None


class IrDocsCollector:
    """IR ページのHTMLを取得し、PDFを抽出してテキスト化する."""

    def __init__(
        self,
        registry: IrPageRegistry,
        *,
        cache_dir: Path | None = None,
        html_fetcher: Any = None,
        pdf_fetcher: Any = None,
        text_extractor: Any = None,
    ) -> None:
        self.registry = registry
        self.cache_dir = cache_dir or Path("./.cache/ir_docs")
        self._html_fetcher = html_fetcher
        self._pdf_fetcher = pdf_fetcher
        self._text_extractor = text_extractor

    def _fetch_html(self, url: str) -> str:
        if self._html_fetcher is not None:
            text: str = self._html_fetcher(url)
            return text
        import requests

        resp = requests.get(url, timeout=30, headers={"User-Agent": "QuantMindBot/0.1"})
        resp.raise_for_status()
        return resp.text

    def _fetch_pdf(self, url: str) -> bytes:
        if self._pdf_fetcher is not None:
            data: bytes = self._pdf_fetcher(url)
            return data
        import requests

        resp = requests.get(url, timeout=60, headers={"User-Agent": "QuantMindBot/0.1"})
        resp.raise_for_status()
        return resp.content

    def _extract_text(self, pdf_bytes: bytes) -> str:
        if self._text_extractor is not None:
            extracted: str = self._text_extractor(pdf_bytes)
            return extracted
        import io

        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    def _find_pdf_url(self, html: str, base_url: str, keyword: str) -> str | None:
        for m in PDF_LINK_RE.finditer(html):
            text = m.group("text")
            if keyword in text:
                return urljoin(base_url, m.group("href"))
        return None

    def collect_one(self, entry: RegistryEntry) -> IrDocsResult:
        keyword = entry.pdf_link_pattern or DEFAULT_KEYWORD
        try:
            html = self._fetch_html(entry.ir_page_url)
        except Exception as e:
            log.warning("IR HTML fetch failed for %s: %s", entry.code, e)
            return IrDocsResult(entry.code, None, "html_failed", None, error=str(e))

        pdf_url = self._find_pdf_url(html, entry.ir_page_url, keyword)
        if pdf_url is None:
            log.warning("no PDF link with keyword %r on %s", keyword, entry.ir_page_url)
            return IrDocsResult(entry.code, None, "not_found", None)

        try:
            pdf_bytes = self._fetch_pdf(pdf_url)
        except Exception as e:
            log.warning("PDF fetch failed for %s: %s", entry.code, e)
            return IrDocsResult(entry.code, pdf_url, "pdf_failed", None, error=str(e))

        try:
            text = self._extract_text(pdf_bytes)
        except Exception as e:
            log.warning("PDF extract failed for %s: %s", entry.code, e)
            return IrDocsResult(entry.code, pdf_url, "extract_failed", None, error=str(e))

        return IrDocsResult(entry.code, pdf_url, "ok", text)

    def collect_for_codes(self, codes: list[str] | None = None) -> list[IrDocsResult]:
        target_codes = codes or self.registry.codes()
        out: list[IrDocsResult] = []
        for code in target_codes:
            entry = self.registry.get(code)
            if entry is None:
                log.warning("IR registry missing code: %s", code)
                continue
            out.append(self.collect_one(entry))
        return out


def upsert_ir_documents(results: list[IrDocsResult], doc_type: str = "earnings_pres") -> int:
    """ir_documents テーブルに UPSERT。挿入件数を返す."""
    n = 0
    today = date.today()
    with get_conn() as conn:
        for r in results:
            doc_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{r.code}:{r.pdf_url or 'na'}:{today}"))
            conn.execute(
                "INSERT INTO ir_documents(id, code, doc_type, published_at, source_url, body_text, "
                "extraction_status) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET body_text=excluded.body_text, "
                "extraction_status=excluded.extraction_status",
                [doc_id, r.code, doc_type, today, r.pdf_url, r.body_text, r.extraction_status],
            )
            n += 1
    return n
