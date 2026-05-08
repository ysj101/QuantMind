"""Bull/Bear ディベート → ジャッジ統合."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from quantmind.llm.runner import LLMResponse, LLMRunner, log_decision, log_decision_error
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
    conversation_id: str | None = None,
) -> DebateResult:
    """1銘柄に対し Bull → Bear → Judge を順に実行."""
    conversation_id = conversation_id or str(uuid.uuid4())
    bull_template = _load_prompt("bull")
    bear_template = _load_prompt("bear")
    judge_template = _load_prompt("judge")

    bull_prompt = _format_prompt(bull_template, **context.__dict__)
    bull_system_prompt = "You are a careful Japanese equities analyst (Bull)."
    try:
        bull_resp: LLMResponse = bull_runner.run(
            system_prompt=bull_system_prompt,
            user_prompt=bull_prompt,
        )
    except Exception as e:
        if persist:
            log_decision_error(
                code=context.code,
                role="bull",
                model=getattr(bull_runner, "name", "unknown"),
                prompt=bull_prompt,
                system_prompt=bull_system_prompt,
                error=f"{type(e).__name__}: {e}",
                as_of=as_of,
                conversation_id=conversation_id,
            )
        raise
    if persist:
        log_decision(
            code=context.code,
            role="bull",
            response=bull_resp,
            prompt=bull_prompt,
            system_prompt=bull_system_prompt,
            as_of=as_of,
            conversation_id=conversation_id,
        )

    bear_prompt = _format_prompt(
        bear_template,
        bull_text=bull_resp.text,
        **context.__dict__,
    )
    bear_system_prompt = "You are a critical Japanese equities analyst (Bear)."
    try:
        bear_resp: LLMResponse = bear_runner.run(
            system_prompt=bear_system_prompt,
            user_prompt=bear_prompt,
        )
    except Exception as e:
        if persist:
            log_decision_error(
                code=context.code,
                role="bear",
                model=getattr(bear_runner, "name", "unknown"),
                prompt=bear_prompt,
                system_prompt=bear_system_prompt,
                error=f"{type(e).__name__}: {e}",
                as_of=as_of,
                conversation_id=conversation_id,
            )
        raise
    if persist:
        log_decision(
            code=context.code,
            role="bear",
            response=bear_resp,
            prompt=bear_prompt,
            system_prompt=bear_system_prompt,
            as_of=as_of,
            conversation_id=conversation_id,
        )

    judge_prompt = _format_prompt(
        judge_template,
        bull_text=bull_resp.text,
        bear_text=bear_resp.text,
        code=context.code,
        name=context.name,
    )
    judge_system_prompt = "You are a neutral judge. Output JSON only."
    try:
        judge_resp: LLMResponse = judge_runner.run(
            system_prompt=judge_system_prompt,
            user_prompt=judge_prompt,
        )
    except Exception as e:
        if persist:
            log_decision_error(
                code=context.code,
                role="judge",
                model=getattr(judge_runner, "name", "unknown"),
                prompt=judge_prompt,
                system_prompt=judge_system_prompt,
                error=f"{type(e).__name__}: {e}",
                as_of=as_of,
                conversation_id=conversation_id,
            )
        raise

    parsed = _parse_judge_output(judge_resp.text)
    confidence_raw = parsed.get("confidence", 0.0)
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.0

    if persist:
        log_decision(
            code=context.code,
            role="judge",
            response=judge_resp,
            prompt=judge_prompt,
            system_prompt=judge_system_prompt,
            confidence=confidence,
            as_of=as_of,
            conversation_id=conversation_id,
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
    grouped: dict[tuple[str, str], dict[str, tuple[str, float | None]]] = {}
    latest_created: dict[tuple[str, str], Any] = {}
    with get_conn(read_only=True) as conn:
        rows = conn.execute(
            "SELECT code, role, output, confidence, conversation_id, created_at FROM llm_decisions "
            "WHERE as_of_date=? AND role IN ('bull', 'bear', 'judge') "
            "ORDER BY code, created_at DESC, role",
            [as_of],
        ).fetchall()

    for code, role, output, confidence, conversation_id, created_at in rows:
        if code is None or role is None:
            continue
        group_id = str(conversation_id or f"legacy:{code}")
        key = (str(code), group_id)
        by_role = grouped.setdefault(key, {})
        by_role.setdefault(str(role), (str(output or ""), confidence))
        if key not in latest_created or created_at > latest_created[key]:
            latest_created[key] = created_at

    out: list[DebateResult] = []
    for (code, _group_id), by_role in sorted(
        grouped.items(), key=lambda item: (item[0][0], latest_created.get(item[0])), reverse=True
    ):
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
