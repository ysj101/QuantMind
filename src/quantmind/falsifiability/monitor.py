"""反証シナリオ日次監視（定量自動 + 定性LLM再評価）."""

from __future__ import annotations

import json
import logging
import operator as op
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from quantmind.falsifiability.generator import (
    QualitativeTrigger,
    QuantitativeTrigger,
)
from quantmind.llm.runner import LLMRunner, log_decision
from quantmind.storage import get_conn

log = logging.getLogger(__name__)

OPERATORS = {
    "<": op.lt,
    "<=": op.le,
    ">": op.gt,
    ">=": op.ge,
    "==": op.eq,
    "!=": op.ne,
}


@dataclass(frozen=True)
class Alert:
    id: str
    code: str
    scenario_id: str
    triggered_at: datetime
    trigger_kind: str  # quantitative / qualitative
    detail: str


def _window_days(window: str) -> int:
    """``5d`` -> 5、``1d`` -> 1、それ以外は 1。"""
    s = (window or "").strip().lower()
    if s.endswith("d"):
        try:
            return int(s[:-1])
        except ValueError:
            return 1
    return 1


def _eval_quant_trigger(
    conn: Any, code: str, trigger: QuantitativeTrigger, as_of: date
) -> tuple[bool, float | None]:
    """1つの定量トリガーを評価し (発火か, 観測値) を返す."""
    days = _window_days(trigger.window)
    rows = conn.execute(
        "SELECT date, close, volume FROM price_daily WHERE code=? AND date<=? "
        "ORDER BY date DESC LIMIT ?",
        [code, as_of, max(days, 25)],
    ).fetchall()
    if not rows:
        return False, None

    closes = [r[1] for r in rows][::-1]
    volumes = [r[2] for r in rows][::-1]

    metric = trigger.metric.lower()
    value: float | None = None
    if metric in ("price", "close"):
        value = float(closes[-1])
    elif metric == "volume":
        value = float(volumes[-1])
    elif metric == "volume_ratio_20d":
        if len(volumes) >= 21:
            avg = sum(volumes[-21:-1]) / 20
            value = float(volumes[-1] / avg) if avg > 0 else None
    elif metric == "drawdown_pct":
        peak = max(closes)
        value = float((closes[-1] / peak - 1.0) * 100.0) if peak > 0 else None
    elif metric == "ma25_deviation_pct":
        if len(closes) >= 25:
            ma = sum(closes[-25:]) / 25
            value = float((closes[-1] / ma - 1.0) * 100.0) if ma > 0 else None
    elif metric in ("net_income_yoy", "revenue_yoy"):
        col = "net_income" if metric == "net_income_yoy" else "revenue"
        rows_fin = conn.execute(
            f"SELECT fiscal_period, {col} FROM financials WHERE code=? ORDER BY fiscal_period DESC LIMIT 5",
            [code],
        ).fetchall()
        if len(rows_fin) >= 2 and rows_fin[1][1] not in (None, 0):
            cur, prev = rows_fin[0][1], rows_fin[1][1]
            if cur is not None:
                value = float((cur / prev - 1.0) * 100.0)
    else:
        log.debug("unknown metric: %s — skip", trigger.metric)
        return False, None

    if value is None:
        return False, None
    cmp = OPERATORS.get(trigger.operator)
    if cmp is None:
        return False, value
    return bool(cmp(value, trigger.threshold)), value


def _eval_qual_trigger(
    runner: LLMRunner,
    code: str,
    trigger: QualitativeTrigger,
    as_of: date,
    persist: bool = True,
    conn: Any | None = None,
) -> tuple[bool, str]:
    """LLM に直近開示・ニュースを渡して定性トリガー発動を評価.

    既存の DuckDB コネクションがあれば再利用する（同時に複数接続を開かないため）。
    """
    if conn is not None:
        rows = conn.execute(
            "SELECT title, doc_type, disclosed_at FROM disclosures "
            "WHERE code=? AND CAST(disclosed_at AS DATE) BETWEEN ? AND ? "
            "ORDER BY disclosed_at DESC LIMIT 30",
            [code, as_of - timedelta(days=14), as_of],
        ).fetchall()
    else:
        with get_conn(read_only=True) as c:
            rows = c.execute(
                "SELECT title, doc_type, disclosed_at FROM disclosures "
                "WHERE code=? AND CAST(disclosed_at AS DATE) BETWEEN ? AND ? "
                "ORDER BY disclosed_at DESC LIMIT 30",
                [code, as_of - timedelta(days=14), as_of],
            ).fetchall()
    context_block = "\n".join(f"- {r[2]} [{r[1]}] {r[0]}" for r in rows) or "(なし)"

    prompt = (
        "以下の反証シナリオが、最近の開示やニュースで「発動」したかを評価してください。\n"
        "判定は YES/NO で先頭に出力し、その後簡潔な理由を1文で書いてください。\n\n"
        f"# 反証シナリオの定性トリガー\n説明: {trigger.description}\n手がかり: {trigger.hints}\n\n"
        f"# 銘柄: {code}\n# 直近2週間の開示\n{context_block}\n"
    )
    response = runner.run(
        system_prompt="You judge whether a falsification trigger has fired.",
        user_prompt=prompt,
    )
    if persist:
        # log_decision は別接続を開くので、呼び出し側コネクションがある場合は同接続で書き込み
        if conn is not None:
            import uuid as _uuid

            conn.execute(
                "INSERT INTO llm_decisions(id, code, as_of_date, role, model, prompt, output) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    str(_uuid.uuid4()),
                    code,
                    as_of,
                    "falsifiability_monitor",
                    response.model,
                    prompt,
                    response.text,
                ],
            )
        else:
            log_decision(
                code=code, role="falsifiability_monitor", response=response, prompt=prompt, as_of=as_of
            )
    head = response.text.strip()[:5].upper()
    fired = head.startswith("YES")
    return fired, response.text.strip()


def _save_alert(alert: Alert) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO alerts(id, code, scenario_id, triggered_at, trigger_kind, detail) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [alert.id, alert.code, alert.scenario_id, alert.triggered_at, alert.trigger_kind, alert.detail],
        )


def evaluate_all(as_of: date, *, qual_runner: LLMRunner | None = None) -> list[Alert]:
    """active な全シナリオを評価し、発火したものに alerts を発行・状態を更新."""
    alerts: list[Alert] = []

    with get_conn() as conn:
        scenarios = conn.execute(
            "SELECT id, code, quantitative_triggers, qualitative_triggers FROM falsifiability_scenarios "
            "WHERE status='active'"
        ).fetchall()

        for scenario_id, code, quants_raw, quals_raw in scenarios:
            quants = [QuantitativeTrigger(**q) for q in json.loads(quants_raw or "[]")]
            quals = [QualitativeTrigger(**q) for q in json.loads(quals_raw or "[]")]

            triggered = False

            for qt in quants:
                fired, value = _eval_quant_trigger(conn, code, qt, as_of)
                if fired:
                    detail = (
                        f"metric={qt.metric} {qt.operator} {qt.threshold} ({qt.window}); observed={value}"
                    )
                    alert = Alert(
                        id=str(uuid.uuid4()),
                        code=code,
                        scenario_id=scenario_id,
                        triggered_at=datetime.now(),
                        trigger_kind="quantitative",
                        detail=detail,
                    )
                    conn.execute(
                        "INSERT INTO alerts(id, code, scenario_id, triggered_at, trigger_kind, detail) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        [
                            alert.id,
                            alert.code,
                            alert.scenario_id,
                            alert.triggered_at,
                            alert.trigger_kind,
                            alert.detail,
                        ],
                    )
                    alerts.append(alert)
                    triggered = True

            if qual_runner is not None:
                for ql in quals:
                    fired_q, reasoning = _eval_qual_trigger(qual_runner, code, ql, as_of, conn=conn)
                    if fired_q:
                        alert = Alert(
                            id=str(uuid.uuid4()),
                            code=code,
                            scenario_id=scenario_id,
                            triggered_at=datetime.now(),
                            trigger_kind="qualitative",
                            detail=reasoning[:500],
                        )
                        conn.execute(
                            "INSERT INTO alerts(id, code, scenario_id, triggered_at, trigger_kind, detail) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            [
                                alert.id,
                                alert.code,
                                alert.scenario_id,
                                alert.triggered_at,
                                alert.trigger_kind,
                                alert.detail,
                            ],
                        )
                        alerts.append(alert)
                        triggered = True

            if triggered:
                conn.execute(
                    "UPDATE falsifiability_scenarios SET status='triggered', triggered_at=? WHERE id=?",
                    [datetime.now(), scenario_id],
                )
    return alerts
