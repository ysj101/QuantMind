"""Bull/Bear ディベート → ジャッジ統合."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from quantmind.llm.runner import LLMResponse, LLMRunner, log_decision
from quantmind.storage import get_conn

PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass(frozen=True)
class StockContext:
    """ディベートの入力コンテキスト."""

    code: str
    name: str = ""
    technical: str = ""
    disclosures: str = ""
    ir_summary: str = ""
    officers: str = ""


@dataclass
class DebateResult:
    code: str
    recommendation: str
    confidence: float
    summary: str
    bull_text: str
    bear_text: str
    judge_text: str
    key_reasons_for: list[str] = field(default_factory=list)
    key_reasons_against: list[str] = field(default_factory=list)


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")


def _format_prompt(template: str, **kwargs: Any) -> str:
    # 不足フィールドは空文字に
    safe = {k: (v if v is not None else "") for k, v in kwargs.items()}
    return template.format(**safe)


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_judge_output(text: str) -> dict[str, Any]:
    """ジャッジ出力 JSON を堅牢に取り出す."""
    match = _JSON_RE.search(text)
    if not match:
        return {
            "recommendation": "watch",
            "confidence": 0.0,
            "summary": text.strip()[:200],
            "key_reasons_for": [],
            "key_reasons_against": [],
        }
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {
            "recommendation": "watch",
            "confidence": 0.0,
            "summary": text.strip()[:200],
            "key_reasons_for": [],
            "key_reasons_against": [],
        }
    if isinstance(data, dict):
        return data
    return {
        "recommendation": "watch",
        "confidence": 0.0,
        "summary": "",
        "key_reasons_for": [],
        "key_reasons_against": [],
    }


def run_debate(
    bull_runner: LLMRunner,
    bear_runner: LLMRunner,
    judge_runner: LLMRunner,
    context: StockContext,
    *,
    as_of: date | None = None,
    persist: bool = True,
) -> DebateResult:
    """1銘柄に対し Bull → Bear → Judge を順に実行."""
    bull_template = _load_prompt("bull")
    bear_template = _load_prompt("bear")
    judge_template = _load_prompt("judge")

    bull_prompt = _format_prompt(bull_template, **context.__dict__)
    bull_resp: LLMResponse = bull_runner.run(
        system_prompt="You are a careful Japanese equities analyst (Bull).",
        user_prompt=bull_prompt,
    )

    bear_prompt = _format_prompt(
        bear_template,
        bull_text=bull_resp.text,
        **context.__dict__,
    )
    bear_resp: LLMResponse = bear_runner.run(
        system_prompt="You are a critical Japanese equities analyst (Bear).",
        user_prompt=bear_prompt,
    )

    judge_prompt = _format_prompt(
        judge_template,
        bull_text=bull_resp.text,
        bear_text=bear_resp.text,
        code=context.code,
        name=context.name,
    )
    judge_resp: LLMResponse = judge_runner.run(
        system_prompt="You are a neutral judge. Output JSON only.",
        user_prompt=judge_prompt,
    )

    parsed = _parse_judge_output(judge_resp.text)
    confidence_raw = parsed.get("confidence", 0.0)
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.0

    if persist:
        log_decision(
            code=context.code, role="bull", response=bull_resp, prompt=bull_prompt, as_of=as_of
        )
        log_decision(
            code=context.code, role="bear", response=bear_resp, prompt=bear_prompt, as_of=as_of
        )
        log_decision(
            code=context.code,
            role="judge",
            response=judge_resp,
            prompt=judge_prompt,
            confidence=confidence,
            as_of=as_of,
        )

    return DebateResult(
        code=context.code,
        recommendation=str(parsed.get("recommendation", "watch")),
        confidence=confidence,
        summary=str(parsed.get("summary", "")),
        bull_text=bull_resp.text,
        bear_text=bear_resp.text,
        judge_text=judge_resp.text,
        key_reasons_for=list(parsed.get("key_reasons_for") or []),
        key_reasons_against=list(parsed.get("key_reasons_against") or []),
    )


def load_debates(as_of: date) -> list[DebateResult]:
    """保存済み Bull/Bear/Judge の判断ログからディベート結果を復元する."""
    grouped: dict[str, dict[str, tuple[str, float | None]]] = {}
    with get_conn(read_only=True) as conn:
        rows = conn.execute(
            "SELECT code, role, output, confidence FROM llm_decisions "
            "WHERE as_of_date=? AND role IN ('bull', 'bear', 'judge') "
            "ORDER BY code, role, created_at DESC",
            [as_of],
        ).fetchall()

    for code, role, output, confidence in rows:
        if code is None or role is None:
            continue
        by_role = grouped.setdefault(str(code), {})
        by_role.setdefault(str(role), (str(output or ""), confidence))

    out: list[DebateResult] = []
    for code, by_role in sorted(grouped.items()):
        if not {"bull", "bear", "judge"} <= by_role.keys():
            continue
        bull_text = by_role["bull"][0]
        bear_text = by_role["bear"][0]
        judge_text, judge_confidence = by_role["judge"]
        parsed = _parse_judge_output(judge_text)
        confidence_raw = parsed.get("confidence", judge_confidence or 0.0)
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = float(judge_confidence or 0.0)
        out.append(
            DebateResult(
                code=code,
                recommendation=str(parsed.get("recommendation", "watch")),
                confidence=confidence,
                summary=str(parsed.get("summary", "")),
                bull_text=bull_text,
                bear_text=bear_text,
                judge_text=judge_text,
                key_reasons_for=list(parsed.get("key_reasons_for") or []),
                key_reasons_against=list(parsed.get("key_reasons_against") or []),
            )
        )
    return out
