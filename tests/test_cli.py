"""CLI エントリポイントのテスト."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from click.testing import CliRunner

from quantmind.cli import _default_pipeline_context, main
from quantmind.llm import ClaudeCodeRunner, CodexRunner


def test_default_pipeline_context_uses_claude_and_codex() -> None:
    ctx = _default_pipeline_context()

    assert isinstance(ctx.bull_runner, ClaudeCodeRunner)
    assert isinstance(ctx.bear_runner, CodexRunner)
    assert isinstance(ctx.judge_runner, ClaudeCodeRunner)


def test_run_command_enables_llm_debate_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[Any, bool]] = []
    bootstraps: list[tuple[date, int, int]] = []

    monkeypatch.setattr("quantmind.storage.init_db", lambda: tmp_path / "quantmind.duckdb")

    def fake_bootstrap_market_data(
        as_of: date,
        *,
        limit: int = 50,
        lookback_days: int = 45,
    ) -> Any:
        bootstraps.append((as_of, limit, lookback_days))
        return SimpleNamespace(candidates=[object()], price_rows_by_code={"1234": 25})

    monkeypatch.setattr("quantmind.universe.bootstrap_market_data", fake_bootstrap_market_data)

    def fake_run_daily(as_of: date, *, context: Any = None, force: bool = False) -> Any:
        calls.append((context, force))
        return SimpleNamespace(as_of=as_of)

    monkeypatch.setattr("quantmind.pipeline.run_daily", fake_run_daily)
    monkeypatch.setattr(
        "quantmind.report.generate_daily_report",
        lambda *_args, **_kwargs: SimpleNamespace(html=tmp_path / "report.html", pdf=None),
    )

    result = CliRunner().invoke(
        main,
        ["run", "--date", "2026-05-05", "--out", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    assert bootstraps == [(date(2026, 5, 5), 50, 45)]
    assert len(calls) == 1
    context, force = calls[0]
    assert force is False
    assert isinstance(context.bull_runner, ClaudeCodeRunner)
    assert isinstance(context.bear_runner, CodexRunner)
    assert isinstance(context.judge_runner, ClaudeCodeRunner)


def test_run_command_can_disable_llm_debate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[Any, bool]] = []

    monkeypatch.setattr("quantmind.storage.init_db", lambda: tmp_path / "quantmind.duckdb")

    def fake_run_daily(as_of: date, *, context: Any = None, force: bool = False) -> Any:
        calls.append((context, force))
        return SimpleNamespace(as_of=as_of)

    monkeypatch.setattr("quantmind.pipeline.run_daily", fake_run_daily)
    monkeypatch.setattr(
        "quantmind.report.generate_daily_report",
        lambda *_args, **_kwargs: SimpleNamespace(html=tmp_path / "report.html", pdf=None),
    )

    result = CliRunner().invoke(
        main,
        [
            "run",
            "--date",
            "2026-05-05",
            "--out",
            str(tmp_path),
            "--no-discover",
            "--no-llm-debate",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [(None, False)]


def test_run_command_can_force_completed_steps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[Any, bool]] = []

    monkeypatch.setattr("quantmind.storage.init_db", lambda: tmp_path / "quantmind.duckdb")

    def fake_run_daily(as_of: date, *, context: Any = None, force: bool = False) -> Any:
        calls.append((context, force))
        return SimpleNamespace(as_of=as_of)

    monkeypatch.setattr("quantmind.pipeline.run_daily", fake_run_daily)
    monkeypatch.setattr(
        "quantmind.report.generate_daily_report",
        lambda *_args, **_kwargs: SimpleNamespace(html=tmp_path / "report.html", pdf=None),
    )

    result = CliRunner().invoke(
        main,
        ["run", "--date", "2026-05-05", "--out", str(tmp_path), "--no-discover", "--force"],
    )

    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert calls[0][1] is True
