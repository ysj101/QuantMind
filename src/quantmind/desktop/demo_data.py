"""Seed deterministic demo data for desktop E2E checks."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime

from quantmind.storage import get_conn, init_db


def seed_demo_data(as_of: date) -> None:
    """Insert one deterministic day of desktop-visible history."""
    init_db()
    judge = {
        "recommendation": "buy",
        "confidence": 0.82,
        "summary": "出来高急増と当日開示が揃い、短期の検証対象として優先度が高い",
        "key_reasons_for": ["volume_spike", "tdnet_today"],
        "key_reasons_against": ["流動性低下リスク"],
    }
    with get_conn() as conn:
        conn.execute("DELETE FROM llm_decisions WHERE id LIKE 'desktop-demo-%'")
        conn.execute("DELETE FROM alerts WHERE id LIKE 'desktop-demo-%'")
        conn.execute("DELETE FROM falsifiability_scenarios WHERE id LIKE 'desktop-demo-%'")
        conn.execute("DELETE FROM pipeline_runs WHERE id LIKE 'desktop-demo-%'")
        conn.execute("DELETE FROM screening_daily WHERE date=? AND code='1234'", [as_of])
        conn.execute("DELETE FROM macro_regime_daily WHERE date=?", [as_of])

        conn.execute(
            "INSERT INTO macro_regime_daily(date, regime, score, components) VALUES (?, ?, ?, ?)",
            [as_of, "risk_on", 0.71, json.dumps({"vix": 18.4, "n225_vs_ma25": 0.03})],
        )
        conn.execute(
            "INSERT INTO screening_daily(date, code, score, rules_hit, rank) VALUES (?, ?, ?, ?, ?)",
            [as_of, "1234", 4.6, json.dumps(["volume_spike", "tdnet_today"]), 1],
        )
        for idx, (step, status, detail) in enumerate(
            [
                ("regime", "success", "risk_on"),
                ("universe", "success", "2 candidates"),
                ("screening", "success", "1 extracted"),
                ("debate", "success", "conversation desktop-demo-conversation"),
            ],
            start=1,
        ):
            conn.execute(
                "INSERT INTO pipeline_runs(id, run_date, step, status, detail, started_at, finished_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    f"desktop-demo-run-{idx}",
                    as_of,
                    step,
                    status,
                    detail,
                    datetime(as_of.year, as_of.month, as_of.day, 9, idx),
                    datetime(as_of.year, as_of.month, as_of.day, 9, idx, 20),
                ],
            )
        for idx, (role, output, confidence) in enumerate(
            [
                ("bull", "Bull: 小型株の出来高が急増し、当日開示も追い風。", None),
                ("bear", "Bear: 流動性低下と材料一巡の反動には注意。", None),
                ("judge", json.dumps(judge, ensure_ascii=False), 0.82),
            ],
            start=1,
        ):
            conn.execute(
                "INSERT INTO llm_decisions("
                "id, code, as_of_date, role, model, system_prompt, prompt, output, confidence, "
                "conversation_id, duration_sec, created_at"
                ") VALUES (?, '1234', ?, ?, 'demo', ?, ?, ?, ?, 'desktop-demo-conversation', ?, ?)",
                [
                    f"desktop-demo-llm-{idx}",
                    as_of,
                    role,
                    f"{role} system prompt",
                    f"{role} user prompt",
                    output,
                    confidence,
                    0.1 * idx,
                    datetime(as_of.year, as_of.month, as_of.day, 9, 10 + idx),
                ],
            )
        conn.execute(
            "INSERT INTO falsifiability_scenarios("
            "id, code, narrative, quantitative_triggers, qualitative_triggers, status"
            ") VALUES (?, '1234', ?, ?, ?, 'active')",
            [
                "desktop-demo-scenario",
                "出来高が急減し、開示後の買いが続かない場合は仮説を棄却",
                json.dumps(["volume_ratio_20d <= 0.5", "drawdown_pct <= -12"]),
                json.dumps(["追加開示がない", "競合が類似施策を発表"]),
            ],
        )
        conn.execute(
            "INSERT INTO alerts(id, code, scenario_id, trigger_kind, detail) "
            "VALUES ('desktop-demo-alert', '1234', 'desktop-demo-scenario', 'quantitative', 'demo alert')",
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()
    seed_demo_data(date.fromisoformat(args.date))
    print(f"seeded desktop demo data for {args.date}")


if __name__ == "__main__":
    main()
