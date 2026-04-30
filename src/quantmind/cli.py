"""QuantMind CLI エントリポイント."""

from __future__ import annotations

import webbrowser
from datetime import date
from pathlib import Path

import click

from quantmind import __version__


@click.group()
@click.version_option(__version__)
def main() -> None:
    """QuantMind — 日本株AI売買支援システム CLI."""


@main.command()
def info() -> None:
    """バージョン情報を表示."""
    click.echo(f"QuantMind v{__version__}")


@main.command("run")
@click.option("--date", "as_of", default=None, help="対象日 YYYY-MM-DD (既定: 本日)")
@click.option("--out", "out_dir", default="reports", show_default=True, type=click.Path())
@click.option("--pdf/--no-pdf", default=False, help="PDF も生成（weasyprint 必須）")
@click.option("--open/--no-open", "open_browser", default=False, help="生成後に既定ブラウザで開く")
def run_cmd(as_of: str | None, out_dir: str, pdf: bool, open_browser: bool) -> None:
    """日次パイプライン実行 → レポート生成."""
    from quantmind.pipeline import run_daily
    from quantmind.report import generate_daily_report

    target = date.fromisoformat(as_of) if as_of else date.today()
    pipe_result = run_daily(target)
    paths = generate_daily_report(pipe_result, Path(out_dir), pdf=pdf)
    click.echo(f"HTML: {paths.html}")
    if paths.pdf:
        click.echo(f"PDF : {paths.pdf}")
    if open_browser:
        webbrowser.open(paths.html.absolute().as_uri())


@main.command("backtest")
@click.option("--start", required=True)
@click.option("--end", required=True)
@click.option("--out", default="reports/backtest.html", show_default=True, type=click.Path())
def backtest_cmd(start: str, end: str, out: str) -> None:
    """ルールベース戦略のバックテスト."""
    from quantmind.backtest import generate_report, run_backtest

    result = run_backtest(date.fromisoformat(start), date.fromisoformat(end))
    click.echo(f"Sharpe: {result.sharpe:.3f}")
    click.echo(f"MaxDD : {result.max_drawdown:.2%}")
    click.echo(f"Trades: {result.n_trades}")
    out_path = generate_report(result, Path(out))
    click.echo(f"report: {out_path}")


if __name__ == "__main__":
    main()
