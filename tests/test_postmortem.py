"""PostMortem テスト."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from quantmind.learning import create_postmortem, failure_pattern_summary
from quantmind.llm.runner import LLMResponse
from quantmind.portfolio import close_position, open_position
from quantmind.storage import init_db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTMIND_DATA_DIR", str(tmp_path))
    init_db()


PM_OUTPUT = json.dumps(
    {
        "summary": "ターゲットに到達したが利食い後に下落",
        "what_worked": "出来高急増のシグナルが正しく機能",
        "what_missed": "ストップ位置が浅すぎた",
        "improvement": "ATRベースのストップに変更を検討",
        "pattern_tags": ["volume_spike_winner", "stop_too_tight"],
    },
    ensure_ascii=False,
)


class FakeRunner:
    name = "fake"

    def run(self, system_prompt: str, user_prompt: str, timeout: int = 180) -> LLMResponse:
        return LLMResponse(PM_OUTPUT, "fake", PM_OUTPUT, "", 0.0)


def test_create_postmortem_persists() -> None:
    p = open_position("1234", 100, 500.0, entry_date=date(2026, 4, 1))
    closed = close_position(p.id, 600.0, exit_date=date(2026, 4, 5))
    pm = create_postmortem(FakeRunner(), closed.id)
    assert "stop_too_tight" in pm.pattern_tags
    assert pm.code == "1234"


def test_failure_pattern_summary_counts() -> None:
    # 3件作成
    for code in ["1234", "5678", "9012"]:
        p = open_position(code, 100, 500.0, entry_date=date(2026, 4, 1))
        closed = close_position(p.id, 600.0, exit_date=date(2026, 4, 5))
        create_postmortem(FakeRunner(), closed.id)
    counts = dict(failure_pattern_summary())
    assert counts.get("volume_spike_winner") == 3
    assert counts.get("stop_too_tight") == 3


def test_postmortem_handles_unparsable_output() -> None:
    p = open_position("1234", 100, 500.0, entry_date=date(2026, 4, 1))
    closed = close_position(p.id, 600.0, exit_date=date(2026, 4, 5))

    class Bad(FakeRunner):
        def run(self, system_prompt: str, user_prompt: str, timeout: int = 180) -> LLMResponse:
            return LLMResponse("not json", "fake", "not json", "", 0.0)

    pm = create_postmortem(Bad(), closed.id)
    assert pm.summary == ""
    assert pm.pattern_tags == []
