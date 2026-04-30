"""EDINET 書類API クライアント.

EDINET は書類一覧と書類本体（XBRL/PDF）を取得するエンドポイントを提供する。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

DEFAULT_UA = (
    "QuantMindBot/0.1 (+https://github.com/ysj101/QuantMind; personal research use)"
)
LIST_URL = "https://api.edinet-fsa.go.jp/api/v2/documents.json"
DOC_URL = "https://api.edinet-fsa.go.jp/api/v2/documents/{doc_id}"


@dataclass(frozen=True)
class EdinetDocument:
    doc_id: str
    code: str | None  # 4桁証券コード（無い書類もある）
    edinet_code: str
    filer_name: str
    doc_type_code: str
    doc_description: str
    submit_datetime: str  # ISO8601 文字列
    raw: dict[str, Any]


class EdinetClient:
    """EDINET API ラッパ.

    ``fetcher`` を注入することで実通信なしのテストが可能。
    """

    def __init__(
        self,
        api_key: str | None = None,
        user_agent: str = DEFAULT_UA,
        fetcher: Any = None,
        binary_fetcher: Any = None,
    ) -> None:
        self.api_key = api_key
        self.user_agent = user_agent
        self._fetcher = fetcher
        self._binary_fetcher = binary_fetcher

    def _get_json(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        if self._fetcher is not None:
            return self._fetcher(url, params)
        import requests

        if self.api_key:
            params = {**params, "Subscription-Key": self.api_key}
        resp = requests.get(url, params=params, headers={"User-Agent": self.user_agent}, timeout=30)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return data

    def _get_binary(self, url: str, params: dict[str, str]) -> bytes:
        if self._binary_fetcher is not None:
            return self._binary_fetcher(url, params)
        import requests

        if self.api_key:
            params = {**params, "Subscription-Key": self.api_key}
        resp = requests.get(url, params=params, headers={"User-Agent": self.user_agent}, timeout=60)
        resp.raise_for_status()
        return resp.content

    def list_documents(self, d: date) -> list[EdinetDocument]:
        """指定日に提出された全書類のメタデータを返す."""
        data = self._get_json(LIST_URL, {"date": d.isoformat(), "type": "2"})
        results = data.get("results", []) or []
        out: list[EdinetDocument] = []
        for r in results:
            out.append(
                EdinetDocument(
                    doc_id=r.get("docID", ""),
                    code=(r.get("secCode") or "").strip()[:4] or None,
                    edinet_code=r.get("edinetCode", ""),
                    filer_name=r.get("filerName", ""),
                    doc_type_code=r.get("docTypeCode", ""),
                    doc_description=r.get("docDescription", ""),
                    submit_datetime=r.get("submitDateTime", ""),
                    raw=r,
                )
            )
        return out

    def download(self, doc_id: str, kind: str = "xbrl", out_dir: Path | None = None) -> Path:
        """書類本体をダウンロード.

        ``kind``:
        - ``xbrl``  : XBRL（type=1, ZIP）
        - ``pdf``   : PDF（type=2）
        """
        type_code = {"xbrl": "1", "pdf": "2"}[kind]
        url = DOC_URL.format(doc_id=doc_id)
        body = self._get_binary(url, {"type": type_code})
        out_dir = out_dir or Path("./.cache/edinet")
        out_dir.mkdir(parents=True, exist_ok=True)
        suffix = ".zip" if kind == "xbrl" else ".pdf"
        path = out_dir / f"{doc_id}{suffix}"
        # 既存ファイルはスキップ（冪等）
        if not path.exists():
            path.write_bytes(body)
        return path
