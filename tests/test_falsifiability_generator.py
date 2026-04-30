"""反証シナリオ生成テスト."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quantmind.falsifiability import generate_scenario, save_scenario
from quantmind.falsifiability.generator import (
    FalsifiabilityScenario,
    parse_scenario,
    update_status,
)
from quantmind.llm.debate import DebateResult
from quantmind.llm.runner import LLMResponse
from quantmind.storage import get_conn, init_db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTMIND_DATA_DIR", str(tmp_path))
    init_db()


VALID_OUTPUT = json.dumps(
    {
        "narrative": "業績モメンタムが鈍化したり、競合の追随で価格圧力が強まれば崩れる",
        "quantitative_triggers": [
            {"metric": "ma25_deviation_pct", "operator": "<", "threshold": -5.0, "window": "5d"},
            {"metric": "volume_ratio_20d", "operator": "<", "threshold": 0.5, "window": "5d"},
        ],
        "qualitative_triggers": [
            {"description": "競合が類似新製品を発表", "hints": "業界ニュース"}
        ],
    },
    ensure_ascii=False,
)


def _debate(code: str = "1234") -> DebateResult:
    return DebateResult(
        code=code,
        recommendation="buy",
        confidence=0.7,
        summary="業績モメンタム評価",
        bull_text="売上成長加速",
        bear_text="競合リスク",
        judge_text="...",
    )


class FakeRunner:
    name = "fake"

    def __init__(self, output: str) -> None:
        self.output = output

    def run(self, system_prompt: str, user_prompt: str, timeout: int = 180) -> LLMResponse:
        return LLMResponse(
            text=self.output,
            model=self.name,
            raw_stdout=self.output,
            raw_stderr="",
            duration_sec=0.0,
        )


def test_parse_scenario_minimum_triggers() -> None:
    scenario = parse_scenario("1234", VALID_OUTPUT)
    assert len(scenario.quantitative_triggers) >= 2
    assert len(scenario.qualitative_triggers) >= 1
    assert scenario.quantitative_triggers[0].operator == "<"
    assert scenario.quantitative_triggers[0].threshold == -5.0


def test_parse_scenario_rejects_short_triggers() -> None:
    bad = json.dumps(
        {
            "narrative": "x",
            "quantitative_triggers": [
                {"metric": "price", "operator": "<", "threshold": 100, "window": "1d"}
            ],
            "qualitative_triggers": [{"description": "y", "hints": ""}],
        }
    )
    with pytest.raises(ValueError, match="quantitative"):
        parse_scenario("1234", bad)


def test_parse_scenario_rejects_no_qualitative() -> None:
    bad = json.dumps(
        {
            "narrative": "x",
            "quantitative_triggers": [
                {"metric": "price", "operator": "<", "threshold": 100, "window": "1d"},
                {"metric": "volume", "operator": "<", "threshold": 1000, "window": "5d"},
            ],
            "qualitative_triggers": [],
        }
    )
    with pytest.raises(ValueError, match="qualitative"):
        parse_scenario("1234", bad)


def test_generate_scenario_persists() -> None:
    runner = FakeRunner(VALID_OUTPUT)
    scenario = generate_scenario(runner, _debate(), name="テスト株式")
    assert isinstance(scenario, FalsifiabilityScenario)
    with get_conn(read_only=True) as conn:
        row = conn.execute(
            "SELECT code, status, quantitative_triggers FROM falsifiability_scenarios WHERE id=?",
            [scenario.id],
        ).fetchone()
    assert row is not None
    assert row[0] == "1234"
    assert row[1] == "active"
    quants = json.loads(row[2])
    assert len(quants) >= 2


def test_save_scenario_idempotent() -> None:
    scenario = parse_scenario("1234", VALID_OUTPUT)
    save_scenario(scenario)
    save_scenario(scenario)
    with get_conn(read_only=True) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM falsifiability_scenarios WHERE id=?", [scenario.id]
        ).fetchone()
    assert n is not None
    assert n[0] == 1


def test_update_status() -> None:
    scenario = parse_scenario("1234", VALID_OUTPUT)
    save_scenario(scenario)
    from datetime import datetime

    update_status(scenario.id, "triggered", triggered_at=datetime(2026, 5, 1, 9))
    with get_conn(read_only=True) as conn:
        row = conn.execute(
            "SELECT status, triggered_at FROM falsifiability_scenarios WHERE id=?",
            [scenario.id],
        ).fetchone()
    assert row is not None
    assert row[0] == "triggered"
