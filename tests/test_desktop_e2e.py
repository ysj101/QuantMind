from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from quantmind.desktop.demo_data import seed_demo_data
from quantmind.desktop.rpc_server import handle_jsonrpc
from quantmind.storage import get_conn, init_db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTMIND_DATA_DIR", str(tmp_path))
    init_db()


def _rpc(method: str, params: dict[str, object]) -> dict[str, object]:
    response = handle_jsonrpc({"jsonrpc": "2.0", "id": "e2e", "method": method, "params": params})
    assert response is not None
    assert "error" not in response
    return response["result"]  # type: ignore[return-value]


def test_desktop_history_e2e_flow_restores_symbols_and_debate_without_mutation() -> None:
    seed_demo_data(date(2026, 5, 5))
    with get_conn(read_only=True) as conn:
        before = conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0]

    summary = _rpc("desktop.get_daily_summary", {"date": "2026-05-05"})
    symbols = _rpc("desktop.list_extracted_symbols", {"date": "2026-05-05"})
    detail = _rpc("desktop.get_symbol_detail", {"date": "2026-05-05", "code": "1234"})
    runs = _rpc("desktop.list_runs", {"limit": 5})

    with get_conn(read_only=True) as conn:
        after = conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0]

    assert before == after
    assert summary["latest_status"] == "success"
    assert summary["extracted_count"] == 1
    assert symbols[0]["code"] == "1234"
    assert symbols[0]["recommendation"] == "buy"
    assert detail["debate"]["conversation_id"] == "desktop-demo-conversation"
    assert [msg["role"] for msg in detail["debate"]["messages"]] == ["bull", "bear", "judge"]
    assert runs[0]["date"] == "2026-05-05"
