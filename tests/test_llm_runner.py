"""LLMRunner のテスト（subprocess を `echo` で代用）."""

from __future__ import annotations

from pathlib import Path

import pytest

from quantmind.llm import (
    ClaudeCodeRunner,
    CodexRunner,
    LLMResponse,
    LLMRunError,
    LLMRunner,
    log_decision,
)
from quantmind.storage import get_conn, init_db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTMIND_DATA_DIR", str(tmp_path))
    init_db()


def test_protocol() -> None:
    r: LLMRunner = ClaudeCodeRunner(cli_path="cat", extra_args=[])
    assert r.name == "claude_code"


def test_runner_with_cat_echoes_input() -> None:
    """`cat` を CLI として注入し、stdin の内容がそのまま返ることを確認."""
    runner = ClaudeCodeRunner(cli_path="cat", extra_args=[])
    resp = runner.run("you are bull", "analyze 7203")
    assert "you are bull" in resp.text
    assert "analyze 7203" in resp.text
    assert resp.model == "claude_code"


def test_codex_runner_with_cat() -> None:
    runner = CodexRunner(cli_path="cat", extra_args=[])
    resp = runner.run("system", "user")
    assert resp.model == "codex"
    assert "system" in resp.text


def test_codex_runner_pins_compatible_model() -> None:
    runner = CodexRunner(cli_path="codex")

    assert runner._build_command() == [
        "codex",
        "exec",
        "-m",
        "gpt-5.4-mini",
        "-c",
        'model_reasoning_effort="low"',
        "-",
    ]


def test_missing_cli_raises() -> None:
    runner = ClaudeCodeRunner(cli_path="this_cli_does_not_exist_xyz", extra_args=[])
    with pytest.raises(LLMRunError):
        runner.run("s", "u")


def test_failing_cli_raises() -> None:
    """非ゼロ終了コードで LLMRunError."""
    runner = ClaudeCodeRunner(cli_path="false", extra_args=[])
    with pytest.raises(LLMRunError):
        runner.run("s", "u")


def test_log_decision_persists() -> None:
    resp = LLMResponse(text="hello", model="claude_code", raw_stdout="hello", raw_stderr="", duration_sec=0.01)
    did = log_decision(code="1234", role="bull", response=resp, prompt="prompt-x", confidence=0.7)
    assert did
    with get_conn(read_only=True) as conn:
        row = conn.execute(
            "SELECT code, role, model, output, confidence FROM llm_decisions WHERE id=?", [did]
        ).fetchone()
    assert row == ("1234", "bull", "claude_code", "hello", 0.7)
