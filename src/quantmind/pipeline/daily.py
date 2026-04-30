"""[docs/spec.md §4.1] のステップ[1]〜[8]を統合実行する日次オーケストレータ."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date as Date
from datetime import datetime
from typing import Any

from quantmind.falsifiability.monitor import Alert, evaluate_all
from quantmind.llm.debate import DebateResult, StockContext, run_debate
from quantmind.llm.runner import LLMRunner
from quantmind.regime import RegimeResult, classify_regime, save_regime
from quantmind.regime.detector import DEFAULT_CONFIG, RegimeConfig
from quantmind.screening.rule_screener import (
    ScreeningResult,
    save_screening,
    screen,
)
from quantmind.storage import get_conn
from quantmind.universe.builder import (
    UniverseConfig,
    UniverseRow,
    build_universe,
    save_universe_snapshot,
)

log = logging.getLogger(__name__)


@dataclass
class StepResult:
    name: str
    status: str  # success / skipped / failed
    detail: str = ""
    started_at: datetime = field(default_factory=datetime.now)
    finished_at: datetime | None = None


@dataclass
class PipelineContext:
    """パイプラインに外部から注入する設定."""

    bull_runner: LLMRunner | None = None
    bear_runner: LLMRunner | None = None
    judge_runner: LLMRunner | None = None
    qual_runner: LLMRunner | None = None
    falsifiability_runner: LLMRunner | None = None
    universe_config: UniverseConfig = field(default_factory=UniverseConfig)
    regime_config: RegimeConfig = DEFAULT_CONFIG
    macro_inputs_provider: Callable[[Date], dict[str, Any]] | None = None
    top_n_screening: int = 10


@dataclass
class DailyPipelineResult:
    as_of: Date
    regime: RegimeResult | None
    universe: list[UniverseRow] = field(default_factory=list)
    screening: list[ScreeningResult] = field(default_factory=list)
    debates: list[DebateResult] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
    steps: list[StepResult] = field(default_factory=list)


def _record_step(as_of: Date, step: StepResult) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO pipeline_runs(id, run_date, step, status, detail, started_at, finished_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                str(uuid.uuid4()),
                as_of,
                step.name,
                step.status,
                step.detail,
                step.started_at,
                step.finished_at or datetime.now(),
            ],
        )


def _already_done(as_of: Date, step_name: str) -> bool:
    with get_conn(read_only=True) as conn:
        row = conn.execute(
            "SELECT 1 FROM pipeline_runs WHERE run_date=? AND step=? AND status='success' LIMIT 1",
            [as_of, step_name],
        ).fetchone()
    return row is not None


def _step(as_of: Date, name: str, fn: Callable[[], Any], *, force: bool = False) -> tuple[StepResult, Any]:
    """1ステップを実行。冪等性のため既存success行があればスキップ可."""
    if not force and _already_done(as_of, name):
        sr = StepResult(name=name, status="skipped", detail="already done", finished_at=datetime.now())
        _record_step(as_of, sr)
        return sr, None
    sr = StepResult(name=name, status="success")
    try:
        result = fn()
    except Exception as e:
        sr.status = "failed"
        sr.detail = f"{type(e).__name__}: {e}"
        sr.finished_at = datetime.now()
        _record_step(as_of, sr)
        log.exception("step %s failed", name)
        return sr, None
    sr.finished_at = datetime.now()
    _record_step(as_of, sr)
    return sr, result


def run_daily(
    as_of: Date,
    *,
    context: PipelineContext | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> DailyPipelineResult:
    ctx = context or PipelineContext()
    out = DailyPipelineResult(as_of=as_of, regime=None)

    # 1) マクロレジーム判定
    def _regime() -> RegimeResult:
        inputs: dict[str, Any] = {}
        if ctx.macro_inputs_provider:
            inputs = ctx.macro_inputs_provider(as_of)
        result = classify_regime(
            vix=inputs.get("vix"),
            n225_close=inputs.get("n225_close"),
            n225_ma25=inputs.get("n225_ma25"),
            usdjpy=inputs.get("usdjpy"),
            usdjpy_5d_ago=inputs.get("usdjpy_5d_ago"),
            as_of=as_of,
            config=ctx.regime_config,
        )
        if not dry_run:
            save_regime(result)
        return result

    sr, regime = _step(as_of, "regime", _regime, force=force)
    out.steps.append(sr)
    out.regime = regime

    # 2) ユニバース構築
    def _universe() -> list[UniverseRow]:
        rows = build_universe(as_of, config=ctx.universe_config)
        if not dry_run:
            save_universe_snapshot(as_of, rows)
        return rows

    sr, universe = _step(as_of, "universe", _universe, force=force)
    out.steps.append(sr)
    out.universe = universe or []

    # Risk Off の場合は新規シグナル抑制（後段スクリーニング/ディベートをスキップ）
    risk_off = bool(regime and regime.regime == "risk_off")
    if risk_off:
        sr_skip = StepResult(
            name="screening", status="skipped", detail="risk_off", finished_at=datetime.now()
        )
        _record_step(as_of, sr_skip)
        out.steps.append(sr_skip)
    else:
        # 3) ルールベーススクリーニング
        def _screening() -> list[ScreeningResult]:
            results = screen(as_of, top_n=ctx.top_n_screening)
            if not dry_run:
                save_screening(as_of, results)
            return results

        sr, screening = _step(as_of, "screening", _screening, force=force)
        out.steps.append(sr)
        out.screening = screening or []

    # 4) 非構造化情報取得 — 既存収集モジュールに委譲する場所。MVPでは省略可。
    out.steps.append(StepResult(name="ingest", status="skipped", detail="external", finished_at=datetime.now()))

    # 5) Bull/Bearディベート
    if not risk_off and out.screening and ctx.bull_runner and ctx.bear_runner and ctx.judge_runner:
        def _debate() -> list[DebateResult]:
            results: list[DebateResult] = []
            for s in out.screening:
                ctx_obj = StockContext(code=s.code)
                results.append(
                    run_debate(
                        ctx.bull_runner,  # type: ignore[arg-type]
                        ctx.bear_runner,  # type: ignore[arg-type]
                        ctx.judge_runner,  # type: ignore[arg-type]
                        ctx_obj,
                        as_of=as_of,
                        persist=not dry_run,
                    )
                )
            return results

        sr, debates = _step(as_of, "debate", _debate, force=force)
        out.steps.append(sr)
        out.debates = debates or []
    else:
        sr_skip = StepResult(
            name="debate",
            status="skipped",
            detail="risk_off" if risk_off else "no_runners_or_no_signals",
            finished_at=datetime.now(),
        )
        _record_step(as_of, sr_skip)
        out.steps.append(sr_skip)

    # 6) 反証監視 (定量自動 + 定性LLM)
    def _falsifiability() -> list[Alert]:
        if dry_run:
            return []
        return evaluate_all(as_of, qual_runner=ctx.qual_runner)

    sr, alerts = _step(as_of, "falsifiability_monitor", _falsifiability, force=force)
    out.steps.append(sr)
    out.alerts = alerts or []

    return out
