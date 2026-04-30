"""反証シナリオの生成・保存."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from quantmind.llm.debate import DebateResult
from quantmind.llm.runner import LLMRunner, log_decision
from quantmind.storage import get_conn

PROMPT_PATH = Path(__file__).parent / "prompt.txt"

VALID_OPERATORS = {"<=", ">=", "<", ">", "==", "!="}
ALLOWED_METRICS = {
    "price",
    "close",
    "volume",
    "volume_ratio_20d",
    "rsi",
    "drawdown_pct",
    "ma25_deviation_pct",
    "net_income_yoy",
    "revenue_yoy",
}


@dataclass
class QuantitativeTrigger:
    metric: str
    operator: str
    threshold: float
    window: str

    def validate(self) -> None:
        if self.operator not in VALID_OPERATORS:
            raise ValueError(f"invalid operator: {self.operator}")
        # metric は LLM 自由入力を許容するが、自動評価可能なのは ALLOWED_METRICS
        if not isinstance(self.threshold, (int, float)):
            raise ValueError("threshold must be numeric")


@dataclass
class QualitativeTrigger:
    description: str
    hints: str = ""


@dataclass
class FalsifiabilityScenario:
    id: str
    code: str
    narrative: str
    quantitative_triggers: list[QuantitativeTrigger] = field(default_factory=list)
    qualitative_triggers: list[QualitativeTrigger] = field(default_factory=list)
    status: str = "active"
    created_at: datetime = field(default_factory=datetime.now)


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_json(text: str) -> dict[str, Any]:
    m = _JSON_RE.search(text)
    if not m:
        raise ValueError("no JSON object in LLM output")
    return json.loads(m.group(0))


def parse_scenario(code: str, llm_text: str, *, scenario_id: str | None = None) -> FalsifiabilityScenario:
    raw = _parse_json(llm_text)
    quants_raw = raw.get("quantitative_triggers", []) or []
    quals_raw = raw.get("qualitative_triggers", []) or []
    quants = []
    for q in quants_raw:
        threshold = q.get("threshold")
        if isinstance(threshold, str):
            try:
                threshold = float(threshold)
            except ValueError as exc:  # 受入基準: 機械判定可能な形式
                raise ValueError(f"non-numeric threshold: {threshold}") from exc
        trig = QuantitativeTrigger(
            metric=str(q.get("metric", "")).strip(),
            operator=str(q.get("operator", "")).strip(),
            threshold=float(threshold or 0.0),
            window=str(q.get("window", "")).strip(),
        )
        trig.validate()
        quants.append(trig)
    quals = [
        QualitativeTrigger(
            description=str(q.get("description", "")).strip(),
            hints=str(q.get("hints", "")).strip(),
        )
        for q in quals_raw
    ]

    if len(quants) < 2:
        raise ValueError(f"need at least 2 quantitative triggers, got {len(quants)}")
    if len(quals) < 1:
        raise ValueError(f"need at least 1 qualitative trigger, got {len(quals)}")

    return FalsifiabilityScenario(
        id=scenario_id or str(uuid.uuid4()),
        code=code,
        narrative=str(raw.get("narrative", "")).strip(),
        quantitative_triggers=quants,
        qualitative_triggers=quals,
    )


def generate_scenario(
    runner: LLMRunner,
    debate: DebateResult,
    *,
    name: str = "",
    persist: bool = True,
) -> FalsifiabilityScenario:
    """ディベート結果を入力に反証シナリオを生成."""
    template = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = template.format(
        code=debate.code,
        name=name,
        bull_text=debate.bull_text,
        bear_text=debate.bear_text,
        judge_summary=debate.summary,
    )
    response = runner.run(
        system_prompt="You generate falsifiable triggers. Output JSON only.",
        user_prompt=prompt,
    )
    if persist:
        log_decision(
            code=debate.code,
            role="falsifiability_gen",
            response=response,
            prompt=prompt,
        )
    scenario = parse_scenario(debate.code, response.text)
    if persist:
        save_scenario(scenario)
    return scenario


def save_scenario(scenario: FalsifiabilityScenario) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO falsifiability_scenarios(id, code, created_at, narrative, "
            "quantitative_triggers, qualitative_triggers, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "narrative=excluded.narrative, quantitative_triggers=excluded.quantitative_triggers, "
            "qualitative_triggers=excluded.qualitative_triggers, status=excluded.status",
            [
                scenario.id,
                scenario.code,
                scenario.created_at,
                scenario.narrative,
                json.dumps([asdict(q) for q in scenario.quantitative_triggers], ensure_ascii=False),
                json.dumps([asdict(q) for q in scenario.qualitative_triggers], ensure_ascii=False),
                scenario.status,
            ],
        )


def update_status(scenario_id: str, status: str, *, triggered_at: datetime | None = None) -> None:
    """状態遷移: active → triggered → resolved."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE falsifiability_scenarios SET status=?, triggered_at=? WHERE id=?",
            [status, triggered_at, scenario_id],
        )
