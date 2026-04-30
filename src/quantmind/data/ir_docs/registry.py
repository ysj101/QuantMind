"""IR ページ URL レジストリ（YAML ファイルベース）."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class RegistryEntry:
    code: str
    ir_page_url: str
    pdf_link_pattern: str | None = None  # 例: "決算説明" を含むリンクテキスト


class IrPageRegistry:
    """銘柄コード → IR ページ URL のレジストリ."""

    def __init__(self, entries: dict[str, RegistryEntry]) -> None:
        self.entries = entries

    @classmethod
    def from_yaml(cls, path: Path) -> IrPageRegistry:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        entries = {}
        for row in data:
            entry = RegistryEntry(
                code=str(row["code"]),
                ir_page_url=row["ir_page_url"],
                pdf_link_pattern=row.get("pdf_link_pattern"),
            )
            entries[entry.code] = entry
        return cls(entries)

    def codes(self) -> list[str]:
        return sorted(self.entries.keys())

    def get(self, code: str) -> RegistryEntry | None:
        return self.entries.get(code)
