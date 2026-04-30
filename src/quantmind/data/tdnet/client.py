"""TDnet 公式サイトの日次一覧をスクレイピングする最小クライアント.

公式 API は無いため `https://www.release.tdnet.info/inbs/I_list_NNN_YYYYMMDD.html`
（NNN はページ番号）の HTML を順次取得して解析する。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin

DEFAULT_UA = (
    "QuantMindBot/0.1 (+https://github.com/ysj101/QuantMind; personal research use)"
)
BASE_URL = "https://www.release.tdnet.info/inbs/"


@dataclass(frozen=True)
class TdnetEntry:
    code: str
    name: str
    title: str
    disclosed_at: datetime
    pdf_url: str | None
    raw_id: str  # ソース上の一意ID（時刻+code+title hash 等）


def _build_list_url(d: date, page: int) -> str:
    return f"{BASE_URL}I_list_{page:03d}_{d:%Y%m%d}.html"


class TdnetClient:
    """日次の TDnet 開示一覧を取得する."""

    def __init__(
        self,
        user_agent: str = DEFAULT_UA,
        request_interval: float = 1.0,
        max_pages: int = 20,
        fetcher: Any = None,
    ) -> None:
        self.user_agent = user_agent
        self.request_interval = request_interval
        self.max_pages = max_pages
        self._fetcher = fetcher  # テスト注入用 callable: (url) -> str | None

    def _fetch(self, url: str) -> str | None:
        if self._fetcher is not None:
            return self._fetcher(url)
        import requests

        resp = requests.get(url, headers={"User-Agent": self.user_agent}, timeout=30)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text

    def list_for_date(self, d: date) -> list[TdnetEntry]:
        entries: list[TdnetEntry] = []
        for page in range(1, self.max_pages + 1):
            url = _build_list_url(d, page)
            html = self._fetch(url)
            if html is None:
                break
            page_entries = parse_tdnet_list(html, d, base_url=url)
            if not page_entries:
                break
            entries.extend(page_entries)
            time.sleep(self.request_interval)
        return entries


_ROW_RE = re.compile(
    r'<td[^>]*>\s*(?P<time>\d{1,2}:\d{2})\s*</td>'
    r'.*?<td[^>]*>\s*(?P<code>\d{4,5})\s*</td>'
    r'.*?<td[^>]*>\s*(?P<name>[^<]+?)\s*</td>'
    r'.*?<a[^>]*href="(?P<pdf>[^"]+\.pdf)"[^>]*>\s*(?P<title>[^<]+?)\s*</a>',
    re.IGNORECASE | re.DOTALL,
)


def parse_tdnet_list(html: str, d: date, *, base_url: str) -> list[TdnetEntry]:
    """TDnet 日次一覧 HTML から TdnetEntry を抽出する.

    HTML 構造変化に対する頑健性は完全ではない。テスト注入可能な
    fetcher で代替できるよう設計しているため、本番投入時は `fetcher`
    を差し替えることを推奨する。
    """
    out: list[TdnetEntry] = []
    for m in _ROW_RE.finditer(html):
        hour, minute = m.group("time").split(":")
        disclosed_at = datetime(d.year, d.month, d.day, int(hour), int(minute))
        code = m.group("code").strip()
        if len(code) == 5 and code.endswith("0"):
            # 5桁コードは末尾0除去で4桁化（東証拡張表記対応）
            code = code[:4]
        title = m.group("title").strip()
        pdf = urljoin(base_url, m.group("pdf").strip())
        raw_id = f"tdnet:{disclosed_at:%Y%m%d%H%M}:{code}:{abs(hash(title)) & 0xFFFFFF:06x}"
        out.append(
            TdnetEntry(
                code=code,
                name=m.group("name").strip(),
                title=title,
                disclosed_at=disclosed_at,
                pdf_url=pdf,
                raw_id=raw_id,
            )
        )
    return out
