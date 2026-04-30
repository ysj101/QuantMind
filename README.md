# QuantMind

日本株（小型株スイングトレード）向けのAI売買支援システム。LLMを「提案型AIアナリスト」として活用し、売買シグナルと反証シナリオをセットで提示する。発注は人間が手動で行う。

## コンセプト

- **反証可能性の強制（Falsifiability First）**: 各提案に「この判断が崩れるシナリオ」を明文化し、毎日再評価する。
- **小型株の非構造化情報の深読み**: 決算説明PDF・IR発信・役員情報など、アナリストの目が届きにくいテキスト情報をLLMで解釈する。

## ドキュメント

- [docs/overview.md](docs/overview.md) — 概要（v1.0）
- [docs/spec.md](docs/spec.md) — 詳細仕様草案（v0.1）

## 開発環境

```bash
make setup        # uv sync
make lint         # ruff check
make format       # ruff format + fix
make typecheck    # mypy
make test         # pytest
make check        # lint + typecheck + test
make pre-commit   # pre-commit run --all-files
```

`uv` 単体で使うコマンド:

```bash
uv sync                    # 環境同期
uv run pytest              # テスト
uv run ruff check .        # Lint
uv run mypy src            # 型チェック
uv run quantmind info      # CLI 動作確認
```

## ステータス

実装フェーズ。Issue ベースで段階的に構築中（`docs/spec.md` 準拠）。
