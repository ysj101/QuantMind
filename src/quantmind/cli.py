"""QuantMind CLI エントリポイント."""

from __future__ import annotations

import webbrowser
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import click

from quantmind import __version__

if TYPE_CHECKING:
    from quantmind.pipeline import PipelineContext


def _default_pipeline_context() -> PipelineContext:
    """CLI 実行時の標準 LLM 構成を返す."""
    from quantmind.llm import ClaudeCodeRunner, CodexRunner
    from quantmind.pipeline import PipelineContext

    return PipelineContext(
        bull_runner=ClaudeCodeRunner(),
        bear_runner=CodexRunner(),
        judge_runner=ClaudeCodeRunner(),
    )


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
@click.option("--force/--no-force", default=False, help="成功済みステップも再実行する")
@click.option("--discover/--no-discover", default=True, help="小型株候補と株価を取得してから実行")
@click.option("--discover-limit", default=50, show_default=True, type=int, help="取得する小型株候補数")
@click.option(
    "--price-lookback-days",
    default=45,
    show_default=True,
    type=int,
    help="取得する株価履歴の日数",
)
@click.option(
    "--llm-debate/--no-llm-debate",
    default=True,
    show_default=True,
    help="Claude Code と Codex の Bull/Bear ディベートを実行",
)
def run_cmd(
    as_of: str | None,
    out_dir: str,
    pdf: bool,
    open_browser: bool,
    force: bool,
    discover: bool,
    discover_limit: int,
    price_lookback_days: int,
    llm_debate: bool,
) -> None:
    """日次パイプライン実行 → レポート生成."""
    from quantmind.pipeline import run_daily
    from quantmind.report import generate_daily_report
    from quantmind.storage import init_db

    init_db()  # 初回起動時にスキーマを自動作成（冪等）
    target = date.fromisoformat(as_of) if as_of else date.today()
    if discover:
        from quantmind.universe import bootstrap_market_data

        bootstrap = bootstrap_market_data(
            target,
            limit=discover_limit,
            lookback_days=price_lookback_days,
        )
        click.echo(
            "discovered: "
            f"{len(bootstrap.candidates)} candidates; "
            f"prices: {sum(bootstrap.price_rows_by_code.values())} rows"
        )
    context = _default_pipeline_context() if llm_debate else None
    pipe_result = run_daily(target, context=context, force=force)
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
    from quantmind.storage import init_db

    init_db()
    result = run_backtest(date.fromisoformat(start), date.fromisoformat(end))
    click.echo(f"Sharpe: {result.sharpe:.3f}")
    click.echo(f"MaxDD : {result.max_drawdown:.2%}")
    click.echo(f"Trades: {result.n_trades}")
    out_path = generate_report(result, Path(out))
    click.echo(f"report: {out_path}")


if __name__ == "__main__":
    main()
