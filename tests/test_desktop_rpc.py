from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from quantmind.desktop.rpc_server import handle_jsonrpc
from quantmind.storage import get_conn, init_db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTMIND_DATA_DIR", str(tmp_path))
    init_db()


def _seed_rows() -> None:
    judge = {
        "recommendation": "buy",
        "confidence": 0.76,
        "summary": "材料と価格反応が揃っている",
    }
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO screening_daily(date, code, score, rules_hit, rank) "
            "VALUES (?, '1234', 3.5, ?, 1)",
            [date(2026, 5, 5), json.dumps(["tdnet_today"])],
        )
        conn.execute(
            "INSERT INTO llm_decisions("
            "id, code, as_of_date, role, model, system_prompt, prompt, output, "
            "confidence, conversation_id, duration_sec, created_at"
            ") VALUES ('judge-1', '1234', ?, 'judge', 'fake', 'judge system', "
            "'judge prompt', ?, 0.76, 'conversation-1', 0.1, ?)",
            [date(2026, 5, 5), json.dumps(judge, ensure_ascii=False), datetime(2026, 5, 5, 9)],
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


def _request(method: str, params: dict[str, object] | None = None) -> dict[str, object]:
    response = handle_jsonrpc({"jsonrpc": "2.0", "id": "1", "method": method, "params": params or {}})
    assert response is not None
    return response


def test_list_extracted_symbols_rpc_returns_json_schema() -> None:
    _seed_rows()

    response = _request("desktop.list_extracted_symbols", {"date": "2026-05-05"})

    result = response["result"]
    assert isinstance(result, list)
    assert result[0]["date"] == "2026-05-05"
    assert result[0]["code"] == "1234"
    assert result[0]["rules_hit"] == ["tdnet_today"]
    assert result[0]["recommendation"] == "buy"


def test_read_only_rpc_does_not_mutate_pipeline_runs() -> None:
    _seed_rows()
    with get_conn(read_only=True) as conn:
        before = conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0]

    response = _request("desktop.get_daily_summary", {"date": "2026-05-05"})

    with get_conn(read_only=True) as conn:
        after = conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0]
    assert before == after
    assert response["result"]["latest_status"] == "success"


def test_missing_date_returns_stable_empty_summary() -> None:
    response = _request("desktop.get_daily_summary", {"date": "2026-05-06"})

    assert response["result"]["latest_status"] == "missing"
    assert response["result"]["extracted_count"] == 0
    assert response["result"]["steps"] == []


def test_invalid_params_are_jsonrpc_errors() -> None:
    response = _request("desktop.get_symbol_detail", {"date": "bad", "code": "1234"})

    assert "error" in response
    assert response["error"]["code"] == -32602
    assert response["error"]["message"] == "validation_error"


def test_unknown_method_returns_method_not_found() -> None:
    response = _request("desktop.unknown")

    assert response["error"]["code"] == -32601
