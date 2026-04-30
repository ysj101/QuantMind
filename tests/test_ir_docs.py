"""IR PDF コレクタのテスト."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from quantmind.data.ir_docs.collector import (
    IrDocsCollector,
    IrDocsResult,
    upsert_ir_documents,
)
from quantmind.data.ir_docs.registry import IrPageRegistry, RegistryEntry
from quantmind.storage import get_conn, init_db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTMIND_DATA_DIR", str(tmp_path))
    init_db()


def _registry(codes: list[str]) -> IrPageRegistry:
    return IrPageRegistry(
        {c: RegistryEntry(code=c, ir_page_url=f"https://example.com/{c}/ir") for c in codes}
    )


def test_registry_yaml_loading(tmp_path: Path) -> None:
    p = tmp_path / "reg.yaml"
    p.write_text(
        '- {code: "1234", ir_page_url: "https://x/1234"}\n'
        '- {code: "5678", ir_page_url: "https://x/5678", pdf_link_pattern: "投資家向け"}\n',
        encoding="utf-8",
    )
    reg = IrPageRegistry.from_yaml(p)
    assert reg.codes() == ["1234", "5678"]
    e = reg.get("5678")
    assert e is not None
    assert e.pdf_link_pattern == "投資家向け"


SAMPLE_HTML = """
<html><body>
<a href="/decisions/2026q1.pdf">2026年3月期 決算説明資料</a>
<a href="/decisions/notice.pdf">お知らせ</a>
</body></html>
"""


def test_collect_one_happy_path() -> None:
    reg = _registry(["1234"])
    collector = IrDocsCollector(
        reg,
        html_fetcher=lambda url: SAMPLE_HTML,
        pdf_fetcher=lambda url: b"DUMMY-PDF-BYTES",
        text_extractor=lambda b: "決算説明資料の本文テキスト",
    )
    result = collector.collect_one(reg.get("1234"))  # type: ignore[arg-type]
    assert result.extraction_status == "ok"
    assert result.body_text and "本文" in result.body_text
    assert result.pdf_url is not None
    assert "2026q1.pdf" in result.pdf_url


def test_collect_handles_missing_pdf_link(caplog: pytest.LogCaptureFixture) -> None:
    reg = _registry(["1234"])
    collector = IrDocsCollector(
        reg,
        html_fetcher=lambda url: "<html><a href='x.pdf'>関係ない資料</a></html>",
    )
    with caplog.at_level(logging.WARNING):
        result = collector.collect_one(reg.get("1234"))  # type: ignore[arg-type]
    assert result.extraction_status == "not_found"
    assert any("no PDF link" in rec.message for rec in caplog.records)


def test_collect_handles_pdf_fetch_failure(caplog: pytest.LogCaptureFixture) -> None:
    reg = _registry(["1234"])

    def failing(url: str) -> bytes:
        raise RuntimeError("404")

    collector = IrDocsCollector(
        reg,
        html_fetcher=lambda url: SAMPLE_HTML,
        pdf_fetcher=failing,
    )
    with caplog.at_level(logging.WARNING):
        result = collector.collect_one(reg.get("1234"))  # type: ignore[arg-type]
    assert result.extraction_status == "pdf_failed"
    assert result.error == "404"


def test_collect_for_codes_skips_unknown(caplog: pytest.LogCaptureFixture) -> None:
    reg = _registry(["1234"])
    collector = IrDocsCollector(
        reg,
        html_fetcher=lambda url: SAMPLE_HTML,
        pdf_fetcher=lambda url: b"x",
        text_extractor=lambda b: "本文",
    )
    with caplog.at_level(logging.WARNING):
        out = collector.collect_for_codes(["1234", "9999"])
    assert {r.code for r in out} == {"1234"}
    assert any("registry missing" in rec.message for rec in caplog.records)


def test_upsert_ir_documents() -> None:
    results = [
        IrDocsResult(code="1234", pdf_url="https://x.pdf", extraction_status="ok", body_text="本文"),
        IrDocsResult(code="5678", pdf_url=None, extraction_status="not_found", body_text=None),
    ]
    n = upsert_ir_documents(results)
    assert n == 2
    with get_conn(read_only=True) as conn:
        rows = conn.execute(
            "SELECT code, extraction_status FROM ir_documents ORDER BY code"
        ).fetchall()
    assert {r[0] for r in rows} == {"1234", "5678"}


def test_collect_10_codes_minimum() -> None:
    """受入基準: 10銘柄分以上の収集が走り、結果がDBに反映される."""
    codes = [f"{1000 + i:04d}" for i in range(10)]
    reg = _registry(codes)
    collector = IrDocsCollector(
        reg,
        html_fetcher=lambda url: SAMPLE_HTML,
        pdf_fetcher=lambda url: b"x",
        text_extractor=lambda b: "決算説明本文",
    )
    results = collector.collect_for_codes()
    assert len(results) == 10
    assert all(r.extraction_status == "ok" for r in results)
    upsert_ir_documents(results)
    with get_conn(read_only=True) as conn:
        n = conn.execute("SELECT COUNT(DISTINCT code) FROM ir_documents").fetchone()
    assert n is not None and n[0] == 10
