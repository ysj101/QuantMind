"""日次レポート生成（Jinja2 → HTML、任意で PDF）."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from quantmind.pipeline.daily import DailyPipelineResult
from quantmind.portfolio import list_open
from quantmind.storage import get_conn

TEMPLATES_DIR = Path(__file__).parent / "templates"


@dataclass
class ReportPaths:
    html: Path
    pdf: Path | None = None


def _new_entry_action(recommendation: str, confidence: float) -> dict[str, str]:
    rec = recommendation.lower()
    if rec == "buy" and confidence >= 0.65:
        return {
            "key": "entry",
            "label": "買い候補",
            "detail": "エントリー価格・損切り条件を決めて少額エントリーを検討",
        }
    if rec == "buy":
        return {
            "key": "watch",
            "label": "監視",
            "detail": "買い方向だが確信度不足。翌日以降の出来高・開示を確認",
        }
    if rec in {"watch", "hold"}:
        return {
            "key": "watch",
            "label": "監視",
            "detail": "新規買いは保留。材料追加・価格反応を待つ",
        }
    if rec in {"skip", "avoid", "sell"}:
        return {
            "key": "skip",
            "label": "見送り",
            "detail": "根拠不足またはリスク優勢。今日はエントリーしない",
        }
    return {
        "key": "review",
        "label": "要確認",
        "detail": f"LLM推奨={recommendation}。人手で内容確認",
    }


def _holding_action(action: str) -> dict[str, str]:
    mapping = {
        "hold": ("hold", "保有継続", "利確・損切り条件に未到達"),
        "take_profit": ("exit", "利確", "目標価格に到達。売却を検討"),
        "stop_loss": ("exit", "損切り", "損切り価格に到達。撤退を検討"),
        "review": ("review", "要確認", "反証トリガー発動。保有継続の根拠を再確認"),
    }
    key, label, detail = mapping.get(action, ("review", action, "内容確認"))
    return {"key": key, "label": label, "detail": detail}


def _build_recommendations(pipe: DailyPipelineResult) -> list[dict[str, Any]]:
    """ディベート結果と最新の反証シナリオを結合."""
    recs: list[dict[str, Any]] = []
    with get_conn(read_only=True) as conn:
        for d in pipe.debates:
            scenario_row = conn.execute(
                "SELECT narrative, quantitative_triggers, qualitative_triggers "
                "FROM falsifiability_scenarios WHERE code=? ORDER BY created_at DESC LIMIT 1",
                [d.code],
            ).fetchone()
            scenario = None
            if scenario_row:
                scenario = {
                    "narrative": scenario_row[0],
                    "quantitative_triggers": json.loads(scenario_row[1] or "[]"),
                    "qualitative_triggers": json.loads(scenario_row[2] or "[]"),
                }
            action = _new_entry_action(d.recommendation, d.confidence)
            recs.append(
                {
                    "code": d.code,
                    "recommendation": d.recommendation,
                    "action": action,
                    "confidence": d.confidence,
                    "summary": d.summary,
                    "bull_text": d.bull_text,
                    "bear_text": d.bear_text,
                    "scenario": scenario,
                    "target_price": None,
                    "stop_price": None,
                }
            )
    return recs


def _build_holdings(pipe: DailyPipelineResult) -> list[dict[str, Any]]:
    holdings: list[dict[str, Any]] = []
    open_pos = list_open()
    code_alert: dict[str, str] = {}
    for a in pipe.alerts:
        # 保有銘柄に紐づくアラートのみハイライト
        code_alert[a.code] = a.detail

    with get_conn(read_only=True) as conn:
        for p in open_pos:
            current_row = conn.execute(
                "SELECT close FROM price_daily WHERE code=? AND date<=? ORDER BY date DESC LIMIT 1",
                [p.code, pipe.as_of],
            ).fetchone()
            current_price = float(current_row[0]) if current_row else None
            unrealized = (
                (current_price - p.entry_price) * p.qty if current_price is not None else None
            )
            action = "hold"
            if p.target_price is not None and current_price is not None and current_price >= p.target_price:
                action = "take_profit"
            elif p.stop_price is not None and current_price is not None and current_price <= p.stop_price:
                action = "stop_loss"
            elif p.code in code_alert:
                action = "review"
            action_detail = _holding_action(action)
            holdings.append(
                {
                    "code": p.code,
                    "qty": p.qty,
                    "entry_price": p.entry_price,
                    "current_price": current_price,
                    "unrealized_pnl": unrealized,
                    "trigger_alert": code_alert.get(p.code),
                    "action": action,
                    "action_detail": action_detail,
                }
            )
    return holdings


def _build_action_items(
    recommendations: list[dict[str, Any]],
    holdings: list[dict[str, Any]],
    *,
    risk_off: bool,
) -> list[dict[str, str]]:
    if risk_off:
        return [{"code": "-", "label": "新規停止", "detail": "Risk Off のため新規エントリーしない"}]

    items: list[dict[str, str]] = []
    for rec in recommendations:
        action = rec["action"]
        items.append(
            {
                "code": rec["code"],
                "label": action["label"],
                "detail": action["detail"],
            }
        )
    for h in holdings:
        action = h["action_detail"]
        items.append(
            {
                "code": h["code"],
                "label": action["label"],
                "detail": action["detail"],
            }
        )
    return items


def _build_postmortems(as_of: date) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with get_conn(read_only=True) as conn:
        rows = conn.execute(
            "SELECT code, summary, what_worked, what_missed, improvement, pattern_tags "
            "FROM postmortems WHERE CAST(closed_at AS DATE)=?",
            [as_of],
        ).fetchall()
    for r in rows:
        out.append(
            {
                "code": r[0],
                "summary": r[1],
                "what_worked": r[2],
                "what_missed": r[3],
                "improvement": r[4],
                "pattern_tags": (r[5] or "").split(",") if r[5] else [],
            }
        )
    return out


def render_html(pipe: DailyPipelineResult) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("daily.html")

    risk_off = bool(pipe.regime and pipe.regime.regime == "risk_off")
    recommendations = [] if risk_off else _build_recommendations(pipe)
    holdings = _build_holdings(pipe)
    action_items = _build_action_items(recommendations, holdings, risk_off=risk_off)
    postmortems = _build_postmortems(pipe.as_of)

    return template.render(
        as_of=pipe.as_of.isoformat(),
        regime=pipe.regime,
        action_items=action_items,
        recommendations=recommendations,
        holdings=holdings,
        alerts=pipe.alerts,
        postmortems=postmortems,
    )


def generate_daily_report(
    pipe: DailyPipelineResult,
    out_dir: Path,
    *,
    pdf: bool = False,
) -> ReportPaths:
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"{pipe.as_of.isoformat()}.html"
    html = render_html(pipe)
    html_path.write_text(html, encoding="utf-8")

    pdf_path: Path | None = None
    if pdf:
        try:
            import weasyprint

            pdf_path = out_dir / f"{pipe.as_of.isoformat()}.pdf"
            weasyprint.HTML(string=html).write_pdf(str(pdf_path))
        except (ImportError, OSError):
            # weasyprint 未インストール or ネイティブ依存（libgobject等）未解決の場合は HTML のみで継続
            pdf_path = None
    return ReportPaths(html=html_path, pdf=pdf_path)
