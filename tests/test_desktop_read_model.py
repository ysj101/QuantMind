from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from quantmind.desktop import (
    get_daily_summary,
    get_debate_transcript,
    get_symbol_detail,
    list_extracted_symbols,
    list_run_summaries,
    search_history,
)
from quantmind.storage import get_conn, init_db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTMIND_DATA_DIR", str(tmp_path))
    init_db()


def _seed_desktop_rows() -> None:
    judge = {
        "recommendation": "buy",
        "confidence": 0.81,
        "summary": "出来高急増と開示材料が揃っている",
    }
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO screening_daily(date, code, score, rules_hit, rank) "
            "VALUES (?, '1234', 4.2, ?, 1)",
            [date(2026, 5, 5), json.dumps(["volume_spike", "tdnet_today"])],
        )
        conn.execute(
            "INSERT INTO macro_regime_daily(date, regime, score, components) VALUES (?, ?, ?, ?)",
            [date(2026, 5, 5), "risk_on", 0.72, json.dumps({"vix": 18.0})],
        )
        for idx, (role, output, confidence) in enumerate(
            [
                ("bull", "bull output", None),
                ("bear", "bear output", None),
                ("judge", json.dumps(judge, ensure_ascii=False), 0.81),
            ],
            start=1,
        ):
            conn.execute(
                "INSERT INTO llm_decisions(id, code, as_of_date, role, model, prompt, output, confidence, created_at) "
                "VALUES (?, '1234', ?, ?, 'fake', ?, ?, ?, ?)",
                [
                    f"llm-{idx}",
                    date(2026, 5, 5),
                    role,
                    f"{role} prompt",
                    output,
                    confidence,
                    datetime(2026, 5, 5, 9, idx),
                ],
            )
        conn.execute(
            "INSERT INTO pipeline_runs(id, run_date, step, status, detail, started_at, finished_at) "
            "VALUES ('run-1', ?, 'screening', 'success', '', ?, ?)",
            [
                date(2026, 5, 5),
                datetime(2026, 5, 5, 9, 0),
                datetime(2026, 5, 5, 9, 1),
            ],
        )
        conn.execute(
            "INSERT INTO falsifiability_scenarios(id, code, narrative, quantitative_triggers, qualitative_triggers, status) "
            "VALUES ('scenario-1', '1234', '崩れる条件', ?, ?, 'active')",
            [json.dumps(["drawdown_pct"]), json.dumps(["競合リスク"])],
        )
        conn.execute(
            "INSERT INTO alerts(id, code, scenario_id, trigger_kind, detail) "
            "VALUES ('alert-1', '1234', 'scenario-1', 'quantitative', 'drawdown_pct')",
        )


def test_list_extracted_symbols_enriches_screening_with_latest_judge() -> None:
    _seed_desktop_rows()

    symbols = list_extracted_symbols(date(2026, 5, 5))

    assert len(symbols) == 1
    assert symbols[0].code == "1234"
    assert symbols[0].rank == 1
    assert symbols[0].rules_hit == ["volume_spike", "tdnet_today"]
    assert symbols[0].recommendation == "buy"
    assert symbols[0].confidence == pytest.approx(0.81)


def test_debate_transcript_restores_bull_bear_judge_messages() -> None:
    _seed_desktop_rows()

    transcript = get_debate_transcript(date(2026, 5, 5), "1234")

    assert transcript.conversation_id == "2026-05-05:1234"
    assert [msg.role for msg in transcript.messages] == ["bull", "bear", "judge"]
    assert transcript.messages[0].prompt == "bull prompt"


def test_symbol_detail_includes_scenarios_and_alerts() -> None:
    _seed_desktop_rows()

    detail = get_symbol_detail(date(2026, 5, 5), "1234")

    assert detail.extracted is not None
    assert detail.debate.messages
    assert detail.scenarios[0]["id"] == "scenario-1"
    assert detail.alerts[0]["id"] == "alert-1"


def test_daily_summary_and_run_summaries_are_read_only() -> None:
    _seed_desktop_rows()
    with get_conn(read_only=True) as conn:
        before = conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0]

    summary = get_daily_summary(date(2026, 5, 5))
    runs = list_run_summaries()

    with get_conn(read_only=True) as conn:
        after = conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0]
    assert before == after
    assert summary.latest_status == "success"
    assert summary.extracted_count == 1
    assert summary.debate_count == 1
    assert runs[0].date == date(2026, 5, 5)


def test_search_history_filters_recommendation_and_confidence() -> None:
    _seed_desktop_rows()

    assert search_history(recommendation="buy", min_confidence=0.8)[0].code == "1234"
    assert search_history(recommendation="watch") == []
