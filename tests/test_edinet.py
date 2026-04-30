"""EDINET コレクタのテスト."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from quantmind.data.edinet.client import EdinetClient
from quantmind.data.edinet.financials import (
    extract_financials_from_xbrl,
    upsert_financials,
)
from quantmind.data.edinet.officers import (
    extract_officers_from_text,
    upsert_officers,
)
from quantmind.storage import get_conn, init_db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTMIND_DATA_DIR", str(tmp_path))
    init_db()


SAMPLE_LIST = {
    "results": [
        {
            "docID": "S100ABCD",
            "secCode": "12340",
            "edinetCode": "E12345",
            "filerName": "テスト株式会社",
            "docTypeCode": "120",
            "docDescription": "有価証券報告書（第10期）",
            "submitDateTime": "2026-04-30 09:00",
        }
    ]
}

SAMPLE_XBRL = """<xbrl>
<jpcrp:NetSales contextRef="CurrentYearConsolidatedDuration_NonConsolidatedMember">1500000000</jpcrp:NetSales>
<jpcrp:NetSales contextRef="PriorYearConsolidatedDuration">1300000000</jpcrp:NetSales>
<jpcrp:OperatingIncome contextRef="CurrentYearConsolidatedDuration">120000000</jpcrp:OperatingIncome>
<jpcrp:NetIncome contextRef="CurrentYearConsolidatedDuration">80000000</jpcrp:NetIncome>
<jpcrp:Assets contextRef="CurrentYearConsolidatedInstant">5000000000</jpcrp:Assets>
<jpcrp:NetAssets contextRef="CurrentYearConsolidatedInstant">3000000000</jpcrp:NetAssets>
</xbrl>"""

SAMPLE_OFFICERS_TEXT = """
役員の状況
山田 太郎 代表取締役社長 1980年4月当社入社、2020年6月より現職に就任
鈴木 花子 取締役 経理畑出身でCFOとして財務戦略を担当している
佐藤 一郎 監査役 弁護士として企業法務に長年従事してきた経歴を有する
大株主の状況
山田 太郎 1,500,000 12.500
日本マスタートラスト信託銀行株式会社 800,000 6.667
"""


def test_list_documents_with_fake_fetcher() -> None:
    def fetcher(url: str, params: dict[str, str]) -> dict:
        return SAMPLE_LIST

    client = EdinetClient(fetcher=fetcher)
    docs = client.list_documents(date(2026, 4, 30))
    assert len(docs) == 1
    assert docs[0].code == "1234"
    assert docs[0].doc_type_code == "120"


def test_extract_financials_picks_current_year() -> None:
    values = extract_financials_from_xbrl(SAMPLE_XBRL)
    assert values["revenue"] == 1500000000.0
    assert values["operating_income"] == 120000000.0
    assert values["net_income"] == 80000000.0
    assert values["total_assets"] == 5000000000.0
    assert values["total_equity"] == 3000000000.0


def test_upsert_financials_idempotent() -> None:
    values = extract_financials_from_xbrl(SAMPLE_XBRL)
    upsert_financials("1234", "2026FY", values)
    upsert_financials("1234", "2026FY", values)
    with get_conn(read_only=True) as conn:
        rows = conn.execute(
            "SELECT revenue, total_assets FROM financials WHERE code='1234' AND fiscal_period='2026FY'"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == 1500000000.0


def test_extract_officers_finds_president_and_holders() -> None:
    records = extract_officers_from_text(SAMPLE_OFFICERS_TEXT)
    names = {r.name for r in records}
    assert "山田 太郎" in names
    # 大株主構成の保有率もエンリッチされる
    yamada = next(r for r in records if r.name == "山田 太郎")
    assert yamada.holdings_pct == 12.5


def test_upsert_officers_replaces_period() -> None:
    records = extract_officers_from_text(SAMPLE_OFFICERS_TEXT)
    n1 = upsert_officers("1234", "2026FY", records)
    n2 = upsert_officers("1234", "2026FY", records)
    assert n1 == n2
    with get_conn(read_only=True) as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM officers WHERE code='1234' AND fiscal_period='2026FY'"
        ).fetchone()
    assert rows is not None
    assert rows[0] == n1


def test_e2e_one_stock(tmp_path: Path) -> None:
    """1銘柄分の E2E: list → extract → upsert."""
    def fetcher(url: str, params: dict[str, str]) -> dict:
        return SAMPLE_LIST

    client = EdinetClient(fetcher=fetcher)
    docs = client.list_documents(date(2026, 4, 30))
    assert len(docs) == 1
    code = docs[0].code
    assert code == "1234"

    values = extract_financials_from_xbrl(SAMPLE_XBRL)
    upsert_financials(code, "2026FY", values)
    officers = extract_officers_from_text(SAMPLE_OFFICERS_TEXT)
    upsert_officers(code, "2026FY", officers)

    with get_conn(read_only=True) as conn:
        n_fin = conn.execute("SELECT COUNT(*) FROM financials WHERE code=?", [code]).fetchone()
        n_off = conn.execute("SELECT COUNT(*) FROM officers WHERE code=?", [code]).fetchone()
    assert n_fin is not None and n_fin[0] == 1
    assert n_off is not None and n_off[0] >= 1
