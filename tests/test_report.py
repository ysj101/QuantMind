"""日次レポート生成テスト."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from quantmind.falsifiability.monitor import Alert
from quantmind.llm.debate import DebateResult
from quantmind.pipeline import DailyPipelineResult
from quantmind.portfolio import open_position
from quantmind.regime import RegimeResult
from quantmind.report import generate_daily_report, render_html
from quantmind.storage import get_conn, init_db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTMIND_DATA_DIR", str(tmp_path))
    init_db()


def _build_pipe(as_of: date, *, regime: str = "risk_on", with_debates: bool = True) -> DailyPipelineResult:
    pipe = DailyPipelineResult(
        as_of=as_of,
        regime=RegimeResult(
            as_of=as_of, regime=regime, score=0.1 if regime == "risk_on" else 0.7, components={"vix": 14.0}
        ),
    )
    if with_debates:
        pipe.debates = [
            DebateResult(
                code="1234",
                recommendation="buy",
                confidence=0.7,
                summary="モメンタム強い",
                bull_text="売上成長",
                bear_text="競合追随",
                judge_text="...",
                key_reasons_for=["growth"],
                key_reasons_against=["competition"],
            )
        ]
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO falsifiability_scenarios(id, code, narrative, quantitative_triggers, "
                "qualitative_triggers, status) VALUES ('s1', '1234', '崩れる条件', ?, ?, 'active')",
                [
                    json.dumps(
                        [
                            {"metric": "drawdown_pct", "operator": "<=", "threshold": -10, "window": "5d"},
                            {"metric": "volume_ratio_20d", "operator": "<=", "threshold": 0.5, "window": "5d"},
                        ]
                    ),
                    json.dumps([{"description": "競合追随", "hints": "業界ニュース"}]),
                ],
            )
    return pipe


def test_render_risk_on_with_recommendation_includes_scenario() -> None:
    pipe = _build_pipe(date(2026, 4, 30))
    html = render_html(pipe)
    assert "1234" in html
    assert "崩れる条件" in html
    assert "drawdown_pct" in html
    assert "本日は新規推奨なし" not in html


def test_render_risk_off_shows_no_signals_banner() -> None:
    pipe = _build_pipe(date(2026, 4, 30), regime="risk_off", with_debates=False)
    html = render_html(pipe)
    assert "本日は新規推奨なし" in html
    assert "RISK_OFF" in html


def test_render_holdings_with_alerts() -> None:
    open_position("5678", 100, 200.0, scenario_id=None, entry_date=date(2026, 4, 1))
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO price_daily(code, date, open, high, low, close, volume, source) "
            "VALUES ('5678', ?, 200, 210, 190, 220, 100, 'fake')",
            [date(2026, 4, 30)],
        )
    pipe = DailyPipelineResult(as_of=date(2026, 4, 30), regime=None)
    pipe.alerts = [
        Alert(
            id="a1",
            code="5678",
            scenario_id="s1",
            triggered_at=datetime(2026, 4, 30, 10),
            trigger_kind="quantitative",
            detail="drawdown_pct <= -10 (5d); observed=-12.5",
        )
    ]
    html = render_html(pipe)
    assert "5678" in html
    assert "drawdown_pct" in html


def test_generate_daily_report_writes_html(tmp_path: Path) -> None:
    pipe = _build_pipe(date(2026, 4, 30))
    paths = generate_daily_report(pipe, tmp_path)
    assert paths.html.exists()
    assert "1234" in paths.html.read_text(encoding="utf-8")


def test_generate_daily_report_pdf_optional(tmp_path: Path) -> None:
    pipe = _build_pipe(date(2026, 4, 30))
    # weasyprint 未インストールでもエラーにならず HTML のみ生成
    paths = generate_daily_report(pipe, tmp_path, pdf=True)
    assert paths.html.exists()
    # PDFはオプション（環境依存）


def test_postmortem_in_report() -> None:
    as_of = date(2026, 4, 30)
    open_pos = open_position("1234", 100, 500.0, entry_date=date(2026, 4, 1))
    from quantmind.portfolio.state import close_position

    closed = close_position(open_pos.id, 600.0, exit_date=as_of)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO postmortems(id, position_id, code, closed_at, summary, what_worked, what_missed, "
            "improvement, pattern_tags) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                "pm1",
                closed.id,
                "1234",
                datetime(2026, 4, 30, 16),
                "ターゲット到達",
                "出来高シグナルが正しく機能",
                "ストップが浅かった",
                "ATRストップ検討",
                "volume_winner,stop_too_tight",
            ],
        )
    pipe = DailyPipelineResult(as_of=as_of, regime=None)
    html = render_html(pipe)
    assert "ターゲット到達" in html
    assert "volume_winner" in html
    # stoptest_holding_days: 5
    assert (closed.exit_date - closed.entry_date) == timedelta(days=29)
