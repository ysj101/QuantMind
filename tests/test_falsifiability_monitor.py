"""反証シナリオ日次監視テスト."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from quantmind.falsifiability.monitor import evaluate_all
from quantmind.llm.runner import LLMResponse
from quantmind.storage import get_conn, init_db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTMIND_DATA_DIR", str(tmp_path))
    init_db()


def _seed_prices(code: str, end: date, closes: list[float], volumes: list[int]) -> None:
    with get_conn() as conn:
        for i, (c, v) in enumerate(zip(closes, volumes, strict=True)):
            d = end - timedelta(days=len(closes) - 1 - i)
            conn.execute(
                "INSERT INTO price_daily(code, date, open, high, low, close, volume, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'fake')",
                [code, d, c, c + 1, c - 1, c, v],
            )


def _seed_scenario(code: str, scenario_id: str, quants: list[dict], quals: list[dict]) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO falsifiability_scenarios(id, code, narrative, quantitative_triggers, "
            "qualitative_triggers, status) VALUES (?, ?, ?, ?, ?, 'active')",
            [scenario_id, code, "test", json.dumps(quants), json.dumps(quals)],
        )


class FakeRunner:
    name = "fake"

    def __init__(self, output: str) -> None:
        self.output = output

    def run(self, system_prompt: str, user_prompt: str, timeout: int = 180) -> LLMResponse:
        return LLMResponse(self.output, "fake", self.output, "", 0.0)


def test_quant_trigger_drawdown_fires() -> None:
    as_of = date(2026, 4, 30)
    # 直近で 30% ドローダウン
    closes = [1000.0] * 20 + [500.0]
    _seed_prices("1234", as_of, closes=closes, volumes=[10000] * 21)
    _seed_scenario(
        "1234",
        "scn-1",
        [{"metric": "drawdown_pct", "operator": "<=", "threshold": -20.0, "window": "20d"}],
        [{"description": "x", "hints": ""}],
    )
    alerts = evaluate_all(as_of)
    assert len(alerts) == 1
    assert alerts[0].trigger_kind == "quantitative"
    assert "drawdown_pct" in alerts[0].detail
    # 状態が triggered に
    with get_conn(read_only=True) as conn:
        st = conn.execute(
            "SELECT status FROM falsifiability_scenarios WHERE id='scn-1'"
        ).fetchone()
    assert st is not None
    assert st[0] == "triggered"


def test_quant_trigger_volume_ratio_does_not_fire() -> None:
    as_of = date(2026, 4, 30)
    # 出来高常に同じ → ratio は ~1.0
    _seed_prices("1234", as_of, closes=[500.0] * 25, volumes=[10000] * 25)
    _seed_scenario(
        "1234",
        "scn-2",
        [
            # 「volume_ratio_20d <= 0.5」 にはヒットしない
            {"metric": "volume_ratio_20d", "operator": "<=", "threshold": 0.5, "window": "5d"},
        ],
        [{"description": "x", "hints": ""}],
    )
    alerts = evaluate_all(as_of)
    assert len(alerts) == 0


def test_qual_trigger_with_yes_fires(tmp_path: Path) -> None:
    as_of = date(2026, 4, 30)
    _seed_prices("1234", as_of, closes=[500.0] * 25, volumes=[10000] * 25)
    _seed_scenario(
        "1234",
        "scn-3",
        [{"metric": "price", "operator": "<=", "threshold": 0.0, "window": "1d"}],  # 発火しない
        [{"description": "競合追随", "hints": "業界ニュース"}],
    )
    runner = FakeRunner("YES 競合の新製品発表が報道された")
    alerts = evaluate_all(as_of, qual_runner=runner)
    qual = [a for a in alerts if a.trigger_kind == "qualitative"]
    assert len(qual) == 1
    assert "競合" in qual[0].detail


def test_qual_trigger_with_no_does_not_fire() -> None:
    as_of = date(2026, 4, 30)
    _seed_prices("1234", as_of, closes=[500.0] * 25, volumes=[10000] * 25)
    _seed_scenario(
        "1234",
        "scn-4",
        [{"metric": "price", "operator": "<=", "threshold": 0.0, "window": "1d"}],
        [{"description": "x", "hints": ""}],
    )
    runner = FakeRunner("NO 該当する開示は確認されなかった")
    alerts = evaluate_all(as_of, qual_runner=runner)
    assert len(alerts) == 0


def test_alerts_persisted_to_db() -> None:
    as_of = date(2026, 4, 30)
    closes = [1000.0] * 20 + [500.0]
    _seed_prices("1234", as_of, closes=closes, volumes=[10000] * 21)
    _seed_scenario(
        "1234",
        "scn-5",
        [{"metric": "drawdown_pct", "operator": "<=", "threshold": -20.0, "window": "20d"}],
        [{"description": "x", "hints": ""}],
    )
    evaluate_all(as_of)
    with get_conn(read_only=True) as conn:
        rows = conn.execute("SELECT trigger_kind, detail FROM alerts").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "quantitative"
