"""QuantMind CLI エントリポイント."""

from __future__ import annotations

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


if __name__ == "__main__":
    main()
