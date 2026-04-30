"""有価証券報告書から役員情報・大株主構成を抽出する.

XBRL タクソノミに完全準拠せず、テキスト中の代表的な見出しと表組みを
正規表現で抽出する軽量実装。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from quantmind.storage import get_conn

# 役員行: 名前は「姓 名」のように内部に空白を含むケースを許容（最大2語）
# 例: "山田 太郎 代表取締役社長 ..."
_OFFICER_LINE_RE = re.compile(
    r"^\s*(?P<name>[^\s\d]{1,12}(?:\s+[^\s\d]{1,12})?)\s+"
    r"(?P<role>(?:代表取締役[^\s]*社長|代表取締役|取締役|常務|専務|社長|"
    r"監査役|執行役員)[^\s]*?)\s+"
    r"(?P<bio>[^\n]{10,200})",
    re.MULTILINE,
)

# 大株主行: 個人なら「姓 名」、法人なら一語の名称。所有株数・割合が続く。
_HOLDER_LINE_RE = re.compile(
    r"^\s*(?P<name>[^\s\d]{2,40}(?:\s+[^\s\d]{1,12})?)\s+"
    r"(?P<shares>[\d,]+)\s+(?P<pct>\d{1,2}\.\d{1,3})\s*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class OfficerRecord:
    name: str
    role: str
    bio: str
    holdings_pct: float | None


def extract_officers_from_text(text: str) -> list[OfficerRecord]:
    """テキスト本文から役員候補と大株主候補を統合して返す.

    完全な精度は出ないが、社長交代・大株主変動を後段の LLM で再評価する
    入力として十分な粒度を確保する。
    """
    out: list[OfficerRecord] = []
    holders = {m.group("name"): float(m.group("pct")) for m in _HOLDER_LINE_RE.finditer(text)}
    seen: set[tuple[str, str]] = set()
    for m in _OFFICER_LINE_RE.finditer(text):
        key = (m.group("name"), m.group("role"))
        if key in seen:
            continue
        seen.add(key)
        out.append(
            OfficerRecord(
                name=m.group("name").strip(),
                role=m.group("role").strip(),
                bio=m.group("bio").strip(),
                holdings_pct=holders.get(m.group("name").strip()),
            )
        )
    # 役員リストになく大株主だけ取れた個人/法人もエントリ追加
    for name, pct in holders.items():
        if not any(o.name == name for o in out):
            out.append(OfficerRecord(name=name, role="shareholder", bio="", holdings_pct=pct))
    return out


def upsert_officers(code: str, fiscal_period: str, records: list[OfficerRecord]) -> int:
    n = 0
    with get_conn() as conn:
        # 同じ code/fiscal_period の既存行は一旦削除して再挿入（簡易的な冪等性）
        conn.execute(
            "DELETE FROM officers WHERE code=? AND fiscal_period=?",
            [code, fiscal_period],
        )
        for r in records:
            conn.execute(
                "INSERT INTO officers(code, fiscal_period, name, role, bio, holdings_pct, raw_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    code,
                    fiscal_period,
                    r.name,
                    r.role,
                    r.bio,
                    r.holdings_pct,
                    json.dumps(r.__dict__, ensure_ascii=False),
                ],
            )
            n += 1
    return n
