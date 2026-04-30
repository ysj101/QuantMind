"""クローズ後の PostMortem 生成."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from quantmind.llm.runner import LLMRunner, log_decision
from quantmind.storage import get_conn

PROMPT_PATH = Path(__file__).parent / "prompt.txt"
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class PostMortem:
    id: str
    position_id: str
    code: str
    summary: str
    what_worked: str
    what_missed: str
    improvement: str
    pattern_tags: list[str]


def _safe_parse(text: str) -> dict[str, Any]:
    m = _JSON_RE.search(text)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def _gather_context(position_id: str) -> dict[str, Any]:
    with get_conn(read_only=True) as conn:
        pos = conn.execute(
            "SELECT id, code, entry_price, entry_date, exit_price, exit_date, realized_pnl, scenario_id "
            "FROM positions WHERE id=?",
            [position_id],
        ).fetchone()
        if pos is None:
            raise ValueError(f"position not found: {position_id}")
        scenario_text = ""
        alerts_text = ""
        debate_summary = ""
        scenario_id = pos[7]
        if scenario_id:
            row = conn.execute(
                "SELECT narrative FROM falsifiability_scenarios WHERE id=?", [scenario_id]
            ).fetchone()
            scenario_text = (row[0] if row else "") or ""
            alert_rows = conn.execute(
                "SELECT triggered_at, trigger_kind, detail FROM alerts WHERE scenario_id=? "
                "ORDER BY triggered_at",
                [scenario_id],
            ).fetchall()
            alerts_text = "\n".join(f"- {a[0]} [{a[1]}] {a[2]}" for a in alert_rows) or "(なし)"
        debate_rows = conn.execute(
            "SELECT output FROM llm_decisions WHERE code=? AND role='judge' ORDER BY created_at DESC LIMIT 1",
            [pos[1]],
        ).fetchone()
        if debate_rows:
            debate_summary = debate_rows[0]
    holding_days = None
    if pos[3] and pos[5]:
        holding_days = (pos[5] - pos[3]).days
    return {
        "code": pos[1],
        "entry_price": pos[2],
        "entry_date": pos[3],
        "exit_price": pos[4],
        "exit_date": pos[5],
        "pnl": pos[6],
        "holding_days": holding_days,
        "scenario_narrative": scenario_text,
        "alerts": alerts_text or "(なし)",
        "debate_summary": debate_summary or "(なし)",
    }


def create_postmortem(runner: LLMRunner, position_id: str) -> PostMortem:
    """ポジションをクローズした後に呼び出して PostMortem を生成・保存する."""
    ctx = _gather_context(position_id)
    template = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = template.format(**ctx)
    response = runner.run(
        system_prompt="You write a postmortem in JSON.",
        user_prompt=prompt,
    )
    log_decision(code=ctx["code"], role="postmortem", response=response, prompt=prompt)
    parsed = _safe_parse(response.text)
    pm = PostMortem(
        id=str(uuid.uuid4()),
        position_id=position_id,
        code=str(ctx["code"]),
        summary=str(parsed.get("summary", "")),
        what_worked=str(parsed.get("what_worked", "")),
        what_missed=str(parsed.get("what_missed", "")),
        improvement=str(parsed.get("improvement", "")),
        pattern_tags=[str(t) for t in (parsed.get("pattern_tags") or [])],
    )
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO postmortems(id, position_id, code, closed_at, summary, what_worked, "
            "what_missed, improvement, pattern_tags) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                pm.id,
                position_id,
                pm.code,
                datetime.now(),
                pm.summary,
                pm.what_worked,
                pm.what_missed,
                pm.improvement,
                ",".join(pm.pattern_tags),
            ],
        )
    return pm


def failure_pattern_summary(top_n: int = 10) -> list[tuple[str, int]]:
    """過去 PostMortem のパターンタグ集計（頻度降順）."""
    with get_conn(read_only=True) as conn:
        rows = conn.execute("SELECT pattern_tags FROM postmortems").fetchall()
    counter: dict[str, int] = {}
    for (raw,) in rows:
        if not raw:
            continue
        for tag in str(raw).split(","):
            tag = tag.strip()
            if not tag:
                continue
            counter[tag] = counter.get(tag, 0) + 1
    return sorted(counter.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
