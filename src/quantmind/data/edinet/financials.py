"""XBRL から主要財務指標を抽出する最小実装.

完全な XBRL タクソノミ対応は重いため、頻出タグの定数マッピングで
売上高・営業利益・純利益・総資産・純資産を取得する単純実装。
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from quantmind.storage import get_conn

# 主要 IFRS / 日本基準タグ（ローカル名）の優先候補
TAG_MAPPING: dict[str, list[str]] = {
    "revenue": ["NetSales", "Revenue", "OperatingRevenue", "NetSalesIFRS"],
    "operating_income": ["OperatingIncome", "OperatingProfit", "OperatingIncomeLoss"],
    "net_income": ["NetIncome", "ProfitLoss", "NetIncomeIFRS"],
    "total_assets": ["Assets", "TotalAssets"],
    "total_equity": ["NetAssets", "Equity", "TotalEquity"],
}

_TAG_RE = re.compile(
    r"<(?:[a-zA-Z0-9_-]+:)?(?P<tag>[A-Za-z0-9_]+)(?P<attrs>[^>]*)>(?P<val>[^<]+)</",
    re.DOTALL,
)
_CONTEXT_RE = re.compile(r'contextRef="([^"]+)"')


def _read_xbrl_text(path: Path) -> str:
    """XBRL ZIP からメインの XBRL テキストを連結して返す。"""
    if path.is_dir():
        files = sorted(path.rglob("*.xbrl"))
        return "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in files)
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as zf:
            chunks: list[str] = []
            for name in zf.namelist():
                if name.lower().endswith(".xbrl"):
                    chunks.append(zf.read(name).decode("utf-8", errors="ignore"))
            return "\n".join(chunks)
    return path.read_text(encoding="utf-8", errors="ignore")


def extract_financials_from_xbrl(path_or_text: Path | str) -> dict[str, float | None]:
    """XBRL から主要指標を抽出.

    ``path_or_text`` がパスならファイルから、文字列ならその文字列を
    XBRL 本文として解析する。
    """
    text = _read_xbrl_text(path_or_text) if isinstance(path_or_text, Path) else path_or_text

    found: dict[str, float | None] = {k: None for k in TAG_MAPPING}
    for m in _TAG_RE.finditer(text):
        tag = m.group("tag")
        attrs = m.group("attrs")
        ctx_m = _CONTEXT_RE.search(attrs)
        # 当期連結値を優先（contextRef が CurrentYear* / Consolidated* を含むもの）
        ctx = ctx_m.group(1) if ctx_m else ""
        if ctx and "Prior" in ctx:
            continue
        val_str = m.group("val").strip().replace(",", "")
        try:
            val = float(val_str)
        except ValueError:
            continue
        for metric, candidates in TAG_MAPPING.items():
            if found[metric] is not None:
                continue
            if tag in candidates:
                found[metric] = val
                break
    return found


def upsert_financials(
    code: str,
    fiscal_period: str,
    values: dict[str, float | None],
    *,
    raw_json: dict | None = None,
) -> None:
    payload = {
        "revenue": values.get("revenue"),
        "operating_income": values.get("operating_income"),
        "net_income": values.get("net_income"),
        "total_assets": values.get("total_assets"),
        "total_equity": values.get("total_equity"),
    }
    raw = json.dumps(raw_json or values, ensure_ascii=False)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO financials(code, fiscal_period, revenue, operating_income, net_income, "
            "total_assets, total_equity, raw_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(code, fiscal_period) DO UPDATE SET "
            "revenue=excluded.revenue, operating_income=excluded.operating_income, "
            "net_income=excluded.net_income, total_assets=excluded.total_assets, "
            "total_equity=excluded.total_equity, raw_json=excluded.raw_json",
            [
                code,
                fiscal_period,
                payload["revenue"],
                payload["operating_income"],
                payload["net_income"],
                payload["total_assets"],
                payload["total_equity"],
                raw,
            ],
        )
