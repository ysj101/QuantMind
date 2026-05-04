# QuantMind

日本株（小型株スイングトレード）向けのAI売買支援システム。LLMを「提案型AIアナリスト」として活用し、売買シグナルと反証シナリオをセットで提示する。発注は人間が手動で行う。

## コンセプト

- **反証可能性の強制（Falsifiability First）**: 各提案に「この判断が崩れるシナリオ」を明文化し、毎日再評価する。
- **小型株の非構造化情報の深読み**: 決算説明PDF・IR発信・役員情報など、アナリストの目が届きにくいテキスト情報をLLMで解釈する。

## ドキュメント

- [docs/overview.md](docs/overview.md) — 概要（v1.0）
- [docs/spec.md](docs/spec.md) — 詳細仕様草案（v0.1）

## セットアップ

```bash
make setup          # uv sync --all-extras
make init-db        # DuckDB スキーマ初期化（~/.quantmind/quantmind.duckdb）
```

データ保存先を変えたい場合は `export QUANTMIND_DATA_DIR=/path/to/dir` を `make init-db` の前に設定してください。

## 日常運用

```bash
make info                                    # バージョン確認
make run                                     # 本日の日次パイプライン → reports/YYYY-MM-DD.html
make run DATE=2026-05-05                     # 指定日
make run-open                                # 生成後にブラウザで開く
make run-pdf                                 # PDF も生成（要 weasyprint）
make backtest START=2024-01-01 END=2024-12-31

# データ収集
make prices CODES='7203 6758'                # 株価更新
make tdnet                                   # 当日 TDnet 開示
make edinet                                  # 当日 EDINET 提出書類一覧
make ir REGISTRY=path/to/registry.yaml       # 決算説明資料 PDF

# 分析
make universe                                # ユニバース構築
make screen TOP=10                           # ルールベース Top N

# ポジション
make position-list / position-history / position-summary
```

利用可能なターゲット一覧は `make help` で確認できます。

## 開発

```bash
make lint           # ruff check
make format         # ruff format + fix
make typecheck      # mypy
make test           # pytest
make check          # まとめて全部
make pre-commit     # pre-commit run --all-files
```

## ステータス

実装フェーズ。Issue ベースで段階的に構築中（`docs/spec.md` 準拠）。
