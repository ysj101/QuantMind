"""Read-only desktop view models backed by existing DuckDB tables."""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from quantmind.desktop.schemas import (
    DailySummary,
    DebateMessage,
    DebateTranscript,
    ExtractedSymbol,
    PipelineRunSummary,
    PipelineStepView,
    SymbolDetail,
)
from quantmind.storage import get_conn

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
_ROLE_ORDER = {"bull": 0, "bear": 1, "judge": 2}


def _parse_json_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return [raw] if raw else []
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    return []


def _parse_json_obj(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _parse_judge_output(text: str, confidence: float | None) -> dict[str, Any]:
    match = _JSON_RE.search(text or "")
    if not match:
        return {
            "recommendation": None,
            "confidence": confidence,
            "summary": (text or "").strip()[:200] or None,
        }
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"recommendation": None, "confidence": confidence, "summary": None}
    if not isinstance(parsed, dict):
        return {"recommendation": None, "confidence": confidence, "summary": None}
    out = dict(parsed)
    out.setdefault("confidence", confidence)
    return out


def _latest_status(steps: list[PipelineStepView]) -> str:
    if not steps:
        return "missing"
    if any(step.status == "failed" for step in steps):
        return "failed"
    if any(step.status == "success" for step in steps):
        return "success"
    if any(step.status == "running" for step in steps):
        return "running"
    return steps[-1].status


def _pipeline_steps_for_date(as_of: date) -> list[PipelineStepView]:
    with get_conn(read_only=True) as conn:
        rows = conn.execute(
            "SELECT step, status, detail, started_at, finished_at "
            "FROM pipeline_runs WHERE run_date=? "
            "ORDER BY started_at, finished_at, step",
            [as_of],
        ).fetchall()
    return [
        PipelineStepView(
            name=str(step),
            status=str(status or "missing"),
            detail=str(detail or ""),
            started_at=started_at,
            finished_at=finished_at,
        )
        for step, status, detail, started_at, finished_at in rows
    ]


def list_run_summaries(limit: int = 30) -> list[PipelineRunSummary]:
    """Return pipeline run summaries grouped by run date, newest first."""
    with get_conn(read_only=True) as conn:
        dates = [
            row[0]
            for row in conn.execute(
                "SELECT run_date FROM pipeline_runs "
                "WHERE run_date IS NOT NULL GROUP BY run_date "
                "ORDER BY run_date DESC LIMIT ?",
                [limit],
            ).fetchall()
        ]
    summaries: list[PipelineRunSummary] = []
    for run_date in dates:
        steps = _pipeline_steps_for_date(run_date)
        starts = [step.started_at for step in steps if step.started_at is not None]
        finishes = [step.finished_at for step in steps if step.finished_at is not None]
        summaries.append(
            PipelineRunSummary(
                date=run_date,
                latest_status=_latest_status(steps),
                started_at=min(starts) if starts else None,
                finished_at=max(finishes) if finishes else None,
                steps=steps,
            )
        )
    return summaries


def _latest_judges(as_of: date) -> dict[str, dict[str, Any]]:
    with get_conn(read_only=True) as conn:
        rows = conn.execute(
            """
            SELECT code, output, confidence FROM (
              SELECT code, output, confidence,
                     ROW_NUMBER() OVER (
                       PARTITION BY code ORDER BY created_at DESC, id DESC
                     ) AS rn
              FROM llm_decisions
              WHERE as_of_date=? AND role='judge'
            ) WHERE rn=1
            """,
            [as_of],
        ).fetchall()
    judges: dict[str, dict[str, Any]] = {}
    for code, output, confidence in rows:
        if code is None:
            continue
        judges[str(code)] = _parse_judge_output(str(output or ""), confidence)
    return judges


def list_extracted_symbols(
    as_of: date,
    *,
    code: str | None = None,
    recommendation: str | None = None,
    min_confidence: float | None = None,
) -> list[ExtractedSymbol]:
    """Return ranked screening results enriched with latest judge decision."""
    query = (
        "SELECT date, code, score, rules_hit, rank FROM screening_daily WHERE date=?"
        + (" AND code=?" if code else "")
        + " ORDER BY rank NULLS LAST, score DESC, code"
    )
    params: list[Any] = [as_of]
    if code:
        params.append(code)
    with get_conn(read_only=True) as conn:
        rows = conn.execute(query, params).fetchall()

    judges = _latest_judges(as_of)
    out: list[ExtractedSymbol] = []
    for row_date, row_code, score, rules_raw, rank in rows:
        decision = judges.get(str(row_code), {})
        rec = decision.get("recommendation")
        confidence_raw = decision.get("confidence")
        confidence = float(confidence_raw) if confidence_raw is not None else None
        if recommendation and rec != recommendation:
            continue
        if min_confidence is not None and (confidence is None or confidence < min_confidence):
            continue
        out.append(
            ExtractedSymbol(
                date=row_date,
                code=str(row_code),
                rank=int(rank) if rank is not None else None,
                score=float(score) if score is not None else None,
                rules_hit=_parse_json_list(rules_raw),
                recommendation=str(rec) if rec is not None else None,
                confidence=confidence,
                summary=str(decision.get("summary")) if decision.get("summary") is not None else None,
            )
        )
    return out


def get_debate_transcript(as_of: date, code: str) -> DebateTranscript:
    """Return Bull/Bear/Judge messages for a date/code using best-effort grouping."""
    with get_conn(read_only=True) as conn:
        latest = conn.execute(
            "SELECT conversation_id FROM llm_decisions "
            "WHERE as_of_date=? AND code=? AND role IN ('bull', 'bear', 'judge') "
            "AND conversation_id IS NOT NULL "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            [as_of, code],
        ).fetchone()
        conversation_id = str(latest[0]) if latest and latest[0] is not None else None
        if conversation_id:
            rows = conn.execute(
                "SELECT role, model, system_prompt, prompt, output, confidence, "
                "duration_sec, error, created_at "
                "FROM llm_decisions WHERE as_of_date=? AND code=? AND conversation_id=? "
                "AND role IN ('bull', 'bear', 'judge') "
                "ORDER BY created_at, role",
                [as_of, code, conversation_id],
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT role, model, system_prompt, prompt, output, confidence, "
                "duration_sec, error, created_at "
                "FROM llm_decisions WHERE as_of_date=? AND code=? "
                "AND role IN ('bull', 'bear', 'judge') "
                "ORDER BY created_at, role",
                [as_of, code],
            ).fetchall()
    messages = [
        DebateMessage(
            role=str(role),
            model=str(model) if model is not None else None,
            system_prompt=str(system_prompt) if system_prompt is not None else None,
            prompt=str(prompt) if prompt is not None else None,
            output=str(output or ""),
            confidence=float(confidence) if confidence is not None else None,
            duration_sec=float(duration_sec) if duration_sec is not None else None,
            error=str(error) if error is not None else None,
            created_at=created_at,
        )
        for role, model, system_prompt, prompt, output, confidence, duration_sec, error, created_at in rows
    ]
    messages.sort(key=lambda msg: (_ROLE_ORDER.get(msg.role, 99), msg.created_at is None, msg.created_at))
    conversation_id = conversation_id or (f"{as_of.isoformat()}:{code}" if messages else None)
    return DebateTranscript(
        date=as_of,
        code=code,
        conversation_id=conversation_id,
        messages=messages,
    )


def _symbol_scenarios(code: str) -> list[dict[str, Any]]:
    with get_conn(read_only=True) as conn:
        rows = conn.execute(
            "SELECT id, created_at, narrative, quantitative_triggers, qualitative_triggers, "
            "status, triggered_at FROM falsifiability_scenarios "
            "WHERE code=? ORDER BY created_at DESC",
            [code],
        ).fetchall()
    return [
        {
            "id": str(sid),
            "created_at": created_at,
            "narrative": narrative,
            "quantitative_triggers": _parse_json_list(q_raw),
            "qualitative_triggers": _parse_json_list(ql_raw),
            "status": status,
            "triggered_at": triggered_at,
        }
        for sid, created_at, narrative, q_raw, ql_raw, status, triggered_at in rows
    ]


def _symbol_alerts(code: str) -> list[dict[str, Any]]:
    with get_conn(read_only=True) as conn:
        rows = conn.execute(
            "SELECT id, scenario_id, triggered_at, trigger_kind, detail "
            "FROM alerts WHERE code=? ORDER BY triggered_at DESC",
            [code],
        ).fetchall()
    return [
        {
            "id": str(aid),
            "scenario_id": scenario_id,
            "triggered_at": triggered_at,
            "trigger_kind": trigger_kind,
            "detail": detail,
        }
        for aid, scenario_id, triggered_at, trigger_kind, detail in rows
    ]


def get_symbol_detail(as_of: date, code: str) -> SymbolDetail:
    """Return screening, debate, scenario, and alert details for a symbol/date."""
    matches = list_extracted_symbols(as_of, code=code)
    return SymbolDetail(
        date=as_of,
        code=code,
        extracted=matches[0] if matches else None,
        debate=get_debate_transcript(as_of, code),
        scenarios=_symbol_scenarios(code),
        alerts=_symbol_alerts(code),
    )


def get_daily_summary(as_of: date) -> DailySummary:
    """Return one desktop summary for a trading date."""
    steps = _pipeline_steps_for_date(as_of)
    symbols = list_extracted_symbols(as_of)
    with get_conn(read_only=True) as conn:
        regime_row = conn.execute(
            "SELECT regime, score, components FROM macro_regime_daily WHERE date=?",
            [as_of],
        ).fetchone()
    regime = None
    if regime_row is not None:
        regime = {
            "regime": regime_row[0],
            "score": float(regime_row[1]) if regime_row[1] is not None else None,
            "components": _parse_json_obj(regime_row[2]),
        }
    debate_count = sum(1 for symbol in symbols if symbol.recommendation is not None)
    return DailySummary(
        date=as_of,
        latest_status=_latest_status(steps),
        steps=steps,
        extracted_count=len(symbols),
        debate_count=debate_count,
        regime=regime,
    )


def search_history(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    code: str | None = None,
    recommendation: str | None = None,
    min_confidence: float | None = None,
    pipeline_status: str | None = None,
    limit: int = 100,
) -> list[ExtractedSymbol]:
    """Search historical extracted symbols with UI-oriented filters."""
    clauses = ["1=1"]
    params: list[Any] = []
    if start_date is not None:
        clauses.append("date>=?")
        params.append(start_date)
    if end_date is not None:
        clauses.append("date<=?")
        params.append(end_date)
    if code:
        clauses.append("code=?")
        params.append(code)
    params.append(limit)
    with get_conn(read_only=True) as conn:
        dates = [
            row[0]
            for row in conn.execute(
                f"SELECT DISTINCT date FROM screening_daily WHERE {' AND '.join(clauses)} "
                "ORDER BY date DESC LIMIT ?",
                params,
            ).fetchall()
        ]

    out: list[ExtractedSymbol] = []
    allowed_dates = set(dates)
    if pipeline_status:
        allowed_dates = {
            summary.date
            for summary in list_run_summaries(limit=limit)
            if summary.date in allowed_dates and summary.latest_status == pipeline_status
        }
    for run_date in dates:
        if run_date not in allowed_dates:
            continue
        out.extend(
            list_extracted_symbols(
                run_date,
                code=code,
                recommendation=recommendation,
                min_confidence=min_confidence,
            )
        )
        if len(out) >= limit:
            return out[:limit]
    return out
