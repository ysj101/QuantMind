"""TDnet コレクタのテスト."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from quantmind.data.tdnet import (
    TdnetClient,
    classify_title,
    disclosure_frequency,
    ingest_entries,
)
from quantmind.data.tdnet.client import TdnetEntry, parse_tdnet_list
from quantmind.storage import get_conn, init_db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTMIND_DATA_DIR", str(tmp_path))
    init_db()


SAMPLE_HTML_PAGE_1 = """
<html><body><table>
  <tr>
    <td>15:00</td><td>1234</td><td>テスト株式会社</td>
    <td><a href="012345/00012345.pdf">2026年3月期決算短信〔日本基準〕(連結)</a></td>
  </tr>
  <tr>
    <td>15:30</td><td>5678</td><td>サンプルHD</td>
    <td><a href="012346/00012346.pdf">業績予想の修正に関するお知らせ</a></td>
  </tr>
  <tr>
    <td>16:00</td><td>1234</td><td>テスト株式会社</td>
    <td><a href="012347/00012347.pdf">自己株式の取得状況に関するお知らせ</a></td>
  </tr>
</table></body></html>
"""

SAMPLE_HTML_PAGE_EMPTY = "<html><body><table></table></body></html>"


def test_parse_tdnet_list_extracts_rows() -> None:
    entries = parse_tdnet_list(SAMPLE_HTML_PAGE_1, date(2026, 4, 30), base_url="https://x/")
    assert len(entries) == 3
    assert entries[0].code == "1234"
    assert "決算短信" in entries[0].title
    assert entries[0].pdf_url is not None and entries[0].pdf_url.endswith(".pdf")


def test_classify_title() -> None:
    assert classify_title("2026年3月期決算短信") == "earnings"
    assert classify_title("業績予想の修正") == "forecast_revision"
    assert classify_title("自己株式の取得状況") == "buyback"
    assert classify_title("ナイトセッションのお知らせ") == "other"


def test_client_with_fake_fetcher() -> None:
    pages = {
        # page 001 returns 3 entries, page 002 returns empty
    }

    def fetcher(url: str) -> str | None:
        if url.endswith("I_list_001_20260430.html"):
            return SAMPLE_HTML_PAGE_1
        if url.endswith("I_list_002_20260430.html"):
            return SAMPLE_HTML_PAGE_EMPTY
        return None

    pages_used = pages  # silence unused
    del pages_used
    client = TdnetClient(request_interval=0.0, fetcher=fetcher)
    entries = client.list_for_date(date(2026, 4, 30))
    assert len(entries) == 3


def test_ingest_idempotent() -> None:
    e1 = TdnetEntry(
        code="1234",
        name="テスト",
        title="2026年3月期決算短信",
        disclosed_at=__import__("datetime").datetime(2026, 4, 30, 15, 0),
        pdf_url="https://x/a.pdf",
        raw_id="tdnet:test:1",
    )
    e2 = TdnetEntry(
        code="5678",
        name="サンプル",
        title="業績予想の修正",
        disclosed_at=__import__("datetime").datetime(2026, 4, 30, 15, 30),
        pdf_url="https://x/b.pdf",
        raw_id="tdnet:test:2",
    )
    assert ingest_entries([e1, e2]) == 2
    # 2回目は冪等
    assert ingest_entries([e1, e2]) == 0
    with get_conn(read_only=True) as conn:
        n = conn.execute("SELECT COUNT(*) FROM disclosures").fetchone()
    assert n is not None and n[0] == 2


def test_disclosure_frequency_zero_padded() -> None:
    e = TdnetEntry(
        code="1234",
        name="テスト",
        title="決算短信",
        disclosed_at=__import__("datetime").datetime(2026, 4, 28, 15, 0),
        pdf_url=None,
        raw_id="tdnet:freq:1",
    )
    ingest_entries([e])
    df = disclosure_frequency("1234", end=date(2026, 4, 30), days=5)
    assert len(df) == 5
    # 4/28 のみ count=1
    counts = dict(zip(df["date"], df["count"], strict=True))
    assert counts[date(2026, 4, 28)] == 1
    assert counts[date(2026, 4, 30)] == 0
