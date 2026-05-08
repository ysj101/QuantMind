from __future__ import annotations

import threading
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from quantmind.desktop import service
from quantmind.desktop.schemas import RunDailyOptions
from quantmind.pipeline import DailyPipelineResult, StepResult
from quantmind.storage import init_db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTMIND_DATA_DIR", str(tmp_path))
    init_db()
    monkeypatch.setattr(service, "_RUN_MANAGER", service.DesktopRunManager())


def test_start_daily_run_completes_and_exposes_status(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_execute(options: RunDailyOptions) -> tuple[DailyPipelineResult, SimpleNamespace]:
        result = DailyPipelineResult(as_of=options.date, regime=None)
        result.steps.append(StepResult(name="screening", status="success", detail="ok"))
        return result, SimpleNamespace(html=Path("reports/2026-05-05.html"), pdf=None)

    monkeypatch.setattr(service, "_execute_pipeline", fake_execute)

    handle = service.start_daily_run(
        RunDailyOptions(date=date(2026, 5, 5), discover=False, llm_debate=False)
    )
    status = service.wait_for_run(handle.run_id, timeout=1)

    assert handle.status == "running"
    assert status.status == "success"
    assert status.steps[0].name == "screening"
    assert status.report_html == "reports/2026-05-05.html"


def test_start_daily_run_prevents_concurrent_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    release = threading.Event()

    def slow_execute(options: RunDailyOptions) -> tuple[DailyPipelineResult, SimpleNamespace]:
        release.wait(timeout=2)
        return DailyPipelineResult(as_of=options.date, regime=None), SimpleNamespace(html=Path("x"), pdf=None)

    monkeypatch.setattr(service, "_execute_pipeline", slow_execute)
    first = service.start_daily_run(
        RunDailyOptions(date=date(2026, 5, 5), discover=False, llm_debate=False)
    )

    with pytest.raises(service.DesktopServiceError) as exc:
        service.start_daily_run(
            RunDailyOptions(date=date(2026, 5, 5), discover=False, llm_debate=False)
        )

    release.set()
    service.wait_for_run(first.run_id, timeout=2)
    assert exc.value.kind == "pipeline_running"


def test_missing_llm_cli_is_reported_in_run_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service.shutil, "which", lambda _name: None)

    handle = service.start_daily_run(
        RunDailyOptions(date=date(2026, 5, 5), discover=False, llm_debate=True)
    )
    status = service.wait_for_run(handle.run_id, timeout=1)

    assert status.status == "failed"
    assert status.detail.startswith("cli_missing:")
