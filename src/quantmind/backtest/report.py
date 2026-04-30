"""バックテストの簡易HTMLレポート."""

from __future__ import annotations

from pathlib import Path

from quantmind.backtest.engine import BacktestResult

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"><title>QuantMind Backtest Report</title>
<style>
body{{font-family:system-ui,'Hiragino Sans','Yu Gothic',sans-serif;margin:24px;color:#222;}}
h1{{border-bottom:2px solid #444;padding-bottom:6px;}}
table{{border-collapse:collapse;margin-top:8px;}}
th,td{{border:1px solid #999;padding:4px 12px;text-align:right;}}
th{{background:#f4f4f4;}}
.summary td:first-child, .summary th:first-child{{text-align:left;}}
.equity{{margin-top:24px;}}
</style></head><body>
<h1>バックテスト結果</h1>
<table class="summary"><tr><th>項目</th><th>値</th></tr>
<tr><td>シャープレシオ（年率）</td><td>{sharpe:.3f}</td></tr>
<tr><td>最大ドローダウン</td><td>{max_drawdown:.2%}</td></tr>
<tr><td>勝率</td><td>{win_rate:.2%}</td></tr>
<tr><td>プロフィットファクター</td><td>{profit_factor:.3f}</td></tr>
<tr><td>平均保有日数</td><td>{avg_holding_days:.1f}</td></tr>
<tr><td>取引回数</td><td>{n_trades}</td></tr>
</table>
<div class="equity">
<h2>資産曲線</h2>
<table><tr><th>日付</th><th>評価額</th></tr>
{rows}
</table>
</div>
</body></html>"""


def generate_report(result: BacktestResult, out_path: Path) -> Path:
    rows = "\n".join(
        f"<tr><td>{d.isoformat()}</td><td>{v:,.0f}</td></tr>" for d, v in result.equity_curve
    )
    html = HTML_TEMPLATE.format(
        sharpe=result.sharpe,
        max_drawdown=result.max_drawdown,
        win_rate=result.win_rate,
        profit_factor=(result.profit_factor if result.profit_factor != float("inf") else 0.0),
        avg_holding_days=result.avg_holding_days,
        n_trades=result.n_trades,
        rows=rows,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path
