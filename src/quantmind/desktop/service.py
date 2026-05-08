"""Operation service for desktop-triggered daily pipeline runs."""

from __future__ import annotations

import shutil
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from quantmind.desktop.schemas import (
    PipelineStepView,
    RunDailyHandle,
    RunDailyOptions,
    RunDailyStatus,
)
from quantmind.pipeline import DailyPipelineResult


@dataclass(frozen=True)
class DesktopServiceError(Exception):
    kind: str
    detail: str


@dataclass
class _RunRecord:
    run_id: str
    options: RunDailyOptions
    status: str = "running"
    detail: str = ""
    started_at: datetime = field(default_factory=datetime.now)
    finished_at: datetime | None = None
    steps: list[PipelineStepView] | None = None
    report_html: str | None = None
    report_pdf: str | None = None

    def to_status(self) -> RunDailyStatus:
        return RunDailyStatus(
            run_id=self.run_id,
            date=self.options.date,
            status=self.status,
            detail=self.detail,
            started_at=self.started_at,
            finished_at=self.finished_at,
            steps=self.steps or [],
            report_html=self.report_html,
            report_pdf=self.report_pdf,
        )


def _ensure_llm_clis() -> None:
    missing = [name for name in ("claude", "codex") if shutil.which(name) is None]
    if missing:
        raise DesktopServiceError(
            "cli_missing",
            "Required LLM CLI not found: " + ", ".join(missing),
        )


def _default_pipeline_context() -> Any:
    from quantmind.cli import _default_pipeline_context as cli_default_pipeline_context

    return cli_default_pipeline_context()


def _execute_pipeline(options: RunDailyOptions) -> tuple[DailyPipelineResult, Any]:
    from quantmind.pipeline import run_daily
    from quantmind.report import generate_daily_report
    from quantmind.storage import init_db

    init_db()
    if options.discover:
        from quantmind.universe import bootstrap_market_data

        bootstrap_market_data(
            options.date,
            limit=options.discover_limit,
            lookback_days=options.price_lookback_days,
        )
    context = None
    if options.llm_debate:
        _ensure_llm_clis()
        context = _default_pipeline_context()
    pipe_result = run_daily(options.date, context=context, force=options.force)
    paths = generate_daily_report(pipe_result, Path(options.out_dir), pdf=options.pdf)
    return pipe_result, paths


class DesktopRunManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, _RunRecord] = {}
        self._active_run_id: str | None = None
        self._threads: dict[str, threading.Thread] = {}

    def start(self, options: RunDailyOptions) -> RunDailyHandle:
        with self._lock:
            if self._active_run_id is not None:
                active = self._runs[self._active_run_id]
                if active.status == "running":
                    raise DesktopServiceError(
                        "pipeline_running",
                        f"Pipeline run {active.run_id} is already running",
                    )
            run_id = str(uuid.uuid4())
            record = _RunRecord(run_id=run_id, options=options, started_at=datetime.now())
            self._runs[run_id] = record
            self._active_run_id = run_id
            thread = threading.Thread(target=self._run, args=(run_id,), daemon=True)
            self._threads[run_id] = thread
            thread.start()
        return RunDailyHandle(run_id=run_id, date=options.date, status="running")

    def _run(self, run_id: str) -> None:
        record = self._runs[run_id]
        try:
            pipe_result, paths = _execute_pipeline(record.options)
            steps = [
                PipelineStepView(
                    name=step.name,
                    status=step.status,
                    detail=step.detail,
                    started_at=step.started_at,
                    finished_at=step.finished_at,
                )
                for step in pipe_result.steps
            ]
            failed = [step for step in steps if step.status == "failed"]
            record.status = "failed" if failed else "success"
            record.detail = "; ".join(step.detail for step in failed if step.detail)
            record.steps = steps
            record.report_html = str(paths.html)
            record.report_pdf = str(paths.pdf) if paths.pdf else None
        except DesktopServiceError as e:
            record.status = "failed"
            record.detail = f"{e.kind}: {e.detail}"
        except Exception as e:
            record.status = "failed"
            record.detail = f"{type(e).__name__}: {e}"
        finally:
            record.finished_at = datetime.now()
            with self._lock:
                if self._active_run_id == run_id:
                    self._active_run_id = None

    def status(self, run_id: str) -> RunDailyStatus:
        record = self._runs.get(run_id)
        if record is None:
            raise DesktopServiceError("missing_run", f"Unknown run id: {run_id}")
        return record.to_status()

    def wait(self, run_id: str, timeout: float | None = None) -> RunDailyStatus:
        thread = self._threads.get(run_id)
        if thread is not None:
            thread.join(timeout)
        return self.status(run_id)


_RUN_MANAGER = DesktopRunManager()


def start_daily_run(options: RunDailyOptions) -> RunDailyHandle:
    return _RUN_MANAGER.start(options)


def get_run_status(run_id: str) -> RunDailyStatus:
    return _RUN_MANAGER.status(run_id)


def wait_for_run(run_id: str, timeout: float | None = None) -> RunDailyStatus:
    return _RUN_MANAGER.wait(run_id, timeout)
