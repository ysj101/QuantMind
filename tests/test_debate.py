"""Bull/Bear ディベートのテスト（モック LLMRunner で検証）."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from quantmind.llm import StockContext, run_debate
from quantmind.llm.runner import LLMResponse
from quantmind.storage import get_conn, init_db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTMIND_DATA_DIR", str(tmp_path))
    init_db()


class FakeRunner:
    name = "fake"

    def __init__(self, output: str) -> None:
        self.output = output
        self.last_prompt: str | None = None

    def run(self, system_prompt: str, user_prompt: str, timeout: int = 180) -> LLMResponse:
        self.last_prompt = user_prompt
        return LLMResponse(
            text=self.output,
            model=self.name,
            raw_stdout=self.output,
            raw_stderr="",
            duration_sec=0.001,
        )


JUDGE_OK = json.dumps(
    {
        "recommendation": "buy",
        "confidence": 0.72,
        "summary": "業績モメンタムは強く反証論も限定的",
        "key_reasons_for": ["売上成長加速", "新製品投入"],
        "key_reasons_against": ["競合追随リスク"],
    },
    ensure_ascii=False,
)


def test_run_debate_happy_path() -> None:
    bull = FakeRunner("- 業績モメンタムは加速")
    bear = FakeRunner("- ただし競合の動向に注意")
    judge = FakeRunner(JUDGE_OK)
    ctx = StockContext(code="1234", name="テスト株式", technical="MA25乖離+10%")
    result = run_debate(bull, bear, judge, ctx, as_of=date(2026, 4, 30))
    assert result.recommendation == "buy"
    assert result.confidence == pytest.approx(0.72)
    assert "業績" in result.summary
    assert result.key_reasons_for == ["売上成長加速", "新製品投入"]


def test_run_debate_persists_three_decisions() -> None:
    bull = FakeRunner("bull text")
    bear = FakeRunner("bear text")
    judge = FakeRunner(JUDGE_OK)
    ctx = StockContext(code="9999")
    run_debate(bull, bear, judge, ctx, as_of=date(2026, 4, 30))
    with get_conn(read_only=True) as conn:
        roles = [
            r[0] for r in conn.execute(
                "SELECT role FROM llm_decisions WHERE code='9999' ORDER BY role"
            ).fetchall()
        ]
    assert roles == ["bear", "bull", "judge"]


def test_judge_output_parser_recovers_from_extra_text() -> None:
    bull = FakeRunner("x")
    bear = FakeRunner("y")
    judge = FakeRunner("Some preamble\n" + JUDGE_OK + "\nMore noise")
    ctx = StockContext(code="2222")
    result = run_debate(bull, bear, judge, ctx, persist=False)
    assert result.recommendation == "buy"


def test_judge_output_parser_handles_garbage() -> None:
    bull = FakeRunner("x")
    bear = FakeRunner("y")
    judge = FakeRunner("not json at all")
    ctx = StockContext(code="3333")
    result = run_debate(bull, bear, judge, ctx, persist=False)
    assert result.recommendation == "watch"
    assert result.confidence == 0.0


def test_bear_receives_bull_text() -> None:
    bull = FakeRunner("BULL_OUTPUT_MARK")
    bear = FakeRunner("bear text")
    judge = FakeRunner(JUDGE_OK)
    run_debate(bull, bear, judge, StockContext(code="4444"), persist=False)
    assert bear.last_prompt is not None
    assert "BULL_OUTPUT_MARK" in bear.last_prompt
