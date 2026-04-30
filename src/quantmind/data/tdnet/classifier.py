"""タイトル文字列から開示種別を簡易分類する."""

from __future__ import annotations

# (キーワード, doc_type) の優先順位リスト
RULES: list[tuple[str, str]] = [
    ("業績予想の修正", "forecast_revision"),
    ("業績予想修正", "forecast_revision"),
    ("配当予想の修正", "dividend_revision"),
    ("自己株式", "buyback"),
    ("自己株取得", "buyback"),
    ("株式分割", "stock_split"),
    ("第三者割当", "third_party_alloc"),
    ("公開買付", "tender_offer"),
    ("ＴＯＢ", "tender_offer"),
    ("M&A", "m_a"),
    ("吸収合併", "m_a"),
    ("株式交換", "m_a"),
    ("決算短信", "earnings"),
    ("四半期報告書", "quarterly_report"),
    ("有価証券報告書", "yuho"),
    ("月次", "monthly"),
]


def classify_title(title: str) -> str:
    for kw, doc_type in RULES:
        if kw in title:
            return doc_type
    return "other"
