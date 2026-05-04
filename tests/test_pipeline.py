"""日次パイプラインオーケストレータテスト."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from quantmind.llm.runner import LLMResponse
from quantmind.pipeline import PipelineContext, run_daily
from quantmind.regime.detector import DEFAULT_CONFIG
from quantmind.storage import get_conn, init_db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTMIND_DATA_DIR", str(tmp_path))
    init_db()


def _seed_universe_and_prices(as_of: date) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO stocks_master(code, name, market, market_cap_jpy) VALUES "
            "('1234', 'A', 'growth', 30_000_000_000), "
            "('5678', 'B', 'standard', 49_000_000_000)"
        )
        # 25日分の価格（出来高急増を仕込む）
        for i in range(25):
            d = as_of - timedelta(days=24 - i)
            for code, base in [("1234", 100.0), ("5678", 200.0)]:
                vol = 10000 if i < 24 else 50000
                conn.execute(
                    "INSERT INTO price_daily(code, date, open, high, low, close, volume, source) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 'fake')",
                    [code, d, base - 1, base + 1, base - 2, base, vol],
                )


class FakeRunner:
    name = "fake"

    def __init__(self, output: str) -> None:
        self.output = output

    def run(self, system_prompt: str, user_prompt: str, timeout: int = 180) -> LLMResponse:
        return LLMResponse(self.output, "fake", self.output, "", 0.0)


JUDGE_OK = json.dumps(
    {"recommendation": "buy", "confidence": 0.7, "summary": "x", "key_reasons_for": ["y"], "key_reasons_against": []},
    ensure_ascii=False,
)


def _calm_inputs(_d: date) -> dict[str, Any]:
    return {
        "vix": 14.0,
        "n225_close": 39000.0,
        "n225_ma25": 38500.0,
        "usdjpy": 150.0,
        "usdjpy_5d_ago": 149.5,
    }


def _stormy_inputs(_d: date) -> dict[str, Any]:
    return {
        "vix": 80.0,
        "n225_close": 17000.0,
        "n225_ma25": 21000.0,
        "usdjpy": 102.0,
        "usdjpy_5d_ago": 110.0,
    }


def test_pipeline_calm_full_run() -> None:
    as_of = date(2026, 4, 30)
    _seed_universe_and_prices(as_of)
    ctx = PipelineContext(
        bull_runner=FakeRunner("bull"),
        bear_runner=FakeRunner("bear"),
        judge_runner=FakeRunner(JUDGE_OK),
        macro_inputs_provider=_calm_inputs,
        regime_config=DEFAULT_CONFIG,
        top_n_screening=5,
    )
    result = run_daily(as_of, context=ctx)
    assert result.regime is not None and result.regime.regime == "risk_on"
    assert len(result.universe) == 2
    # 価格200は price_max=670円以下で included
    assert any(s.code in {"1234", "5678"} for s in result.screening)
    # ディベートも実行される
    assert len(result.debates) >= 1


def test_pipeline_risk_off_skips_screening() -> None:
    as_of = date(2026, 4, 30)
    _seed_universe_and_prices(as_of)
    ctx = PipelineContext(
        bull_runner=FakeRunner("x"),
        bear_runner=FakeRunner("y"),
        judge_runner=FakeRunner(JUDGE_OK),
        macro_inputs_provider=_stormy_inputs,
    )
    result = run_daily(as_of, context=ctx)
    assert result.regime is not None and result.regime.regime == "risk_off"
    skipped = {s.name: s for s in result.steps}
    assert skipped["screening"].status == "skipped"
    assert skipped["screening"].detail == "risk_off"
    assert skipped["debate"].status == "skipped"
    assert result.screening == []
    assert result.debates == []


def test_pipeline_resume_skips_completed_steps() -> None:
    as_of = date(2026, 4, 30)
    _seed_universe_and_prices(as_of)
    ctx = PipelineContext(macro_inputs_provider=_calm_inputs)
    run_daily(as_of, context=ctx)
    result2 = run_daily(as_of, context=ctx)
    statuses = {s.name: s.status for s in result2.steps}
    assert statuses["regime"] == "skipped"
    assert statuses["universe"] == "skipped"
    assert result2.regime is not None and result2.regime.regime == "risk_on"
    assert len(result2.universe) == 2
    assert len(result2.screening) >= 1


def test_pipeline_resume_loads_completed_debates() -> None:
    as_of = date(2026, 4, 30)
    _seed_universe_and_prices(as_of)
    ctx = PipelineContext(
        bull_runner=FakeRunner("bull"),
        bear_runner=FakeRunner("bear"),
        judge_runner=FakeRunner(JUDGE_OK),
        macro_inputs_provider=_calm_inputs,
    )
    run_daily(as_of, context=ctx)

    result2 = run_daily(as_of, context=ctx)

    debate_step = next(s for s in result2.steps if s.name == "debate")
    assert debate_step.status == "skipped"
    assert len(result2.debates) >= 1
    assert result2.debates[0].recommendation == "buy"


def test_dry_run_does_not_persist() -> None:
    as_of = date(2026, 4, 30)
    _seed_universe_and_prices(as_of)
    ctx = PipelineContext(macro_inputs_provider=_calm_inputs)
    run_daily(as_of, context=ctx, dry_run=True)
    with get_conn(read_only=True) as conn:
        n_regime = conn.execute(
            "SELECT COUNT(*) FROM macro_regime_daily WHERE date=?", [as_of]
        ).fetchone()
        n_screen = conn.execute(
            "SELECT COUNT(*) FROM screening_daily WHERE date=?", [as_of]
        ).fetchone()
    assert n_regime is not None and n_regime[0] == 0
    assert n_screen is not None and n_screen[0] == 0


def test_step_failure_records_status() -> None:
    as_of = date(2026, 4, 30)
    # 価格データ無しでスクリーニングが空 → falsifiability_monitor は走るが空
    # 失敗を再現するため、FakeRunner を強制例外に
    class Boom:
        name = "boom"

        def run(self, *a: Any, **k: Any) -> LLMResponse:
            raise RuntimeError("nope")

    _seed_universe_and_prices(as_of)
    ctx = PipelineContext(
        bull_runner=Boom(),
        bear_runner=Boom(),
        judge_runner=Boom(),
        macro_inputs_provider=_calm_inputs,
    )
    result = run_daily(as_of, context=ctx)
    debate_step = next(s for s in result.steps if s.name == "debate")
    # ディベートは例外で failed
    assert debate_step.status == "failed"
