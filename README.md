# QuantMind

日本株（小型株スイングトレード）向けのAI売買支援システム。LLMを「提案型AIアナリスト」として活用し、売買シグナルと反証シナリオをセットで提示する。発注は人間が手動で行う。

## コンセプト

- **反証可能性の強制（Falsifiability First）**: 各提案に「この判断が崩れるシナリオ」を明文化し、毎日再評価する。
- **小型株の非構造化情報の深読み**: 決算説明PDF・IR発信・役員情報など、アナリストの目が届きにくいテキスト情報をLLMで解釈する。

## ドキュメント

- [docs/overview.md](docs/overview.md) — 概要（v1.0）
- [docs/spec.md](docs/spec.md) — 詳細仕様草案（v0.1）
- [docs/desktop-app.md](docs/desktop-app.md) — Electron デスクトップアプリ方針・起動手順
- [docs/desktop-rpc-contract.md](docs/desktop-rpc-contract.md) — Electron IPC / Python JSON-RPC 契約
- [docs/desktop-e2e.md](docs/desktop-e2e.md) — Desktop E2E / 運用確認チェックリスト

## セットアップ

```bash
make setup          # uv sync --all-extras
make desktop-setup  # apps/desktop の pnpm install
make init-db        # DuckDB スキーマ初期化（~/.quantmind/quantmind.duckdb）
```

データ保存先を変えたい場合は `export QUANTMIND_DATA_DIR=/path/to/dir` を `make init-db` の前に設定してください。
日次パイプラインの LLM 議論にはローカルの `claude` CLI と `codex` CLI を使います。未設定の場合は Electron 側の実行ステータスに `cli_missing` として返します。

## 日常運用

通常の確認・実行は Electron の独立 window で行います。

```bash
make info                                    # バージョン確認
make desktop-start                           # renderer build → Electron window 起動
make desktop-dev                             # renderer dev server 起動（開発用）
make desktop-window                          # dev server を Electron window で開く（別 terminal）
make desktop-test                            # desktop typecheck + build
make desktop-demo-data DATE=2026-05-05        # E2E 用のデモ履歴を投入
```

Electron window では、日次サマリ、抽出銘柄、銘柄詳細、Bull/Bear/Judge 議論履歴、pipeline 実行履歴、日次パイプライン実行パネルを確認できます。

HTML/PDF レポートは互換性維持とエクスポート用の補助出力です。

```bash
make run                                     # 日次パイプライン + 補助 HTML レポート
make run DATE=2026-05-05                     # 指定日
make run DATE=2026-05-05 FORCE=--force        # 成功済みステップも再実行
make run DISCOVER=--no-discover               # 小型株候補・株価取得を無効化
make run LLM_DEBATE=--no-llm-debate           # LLM 議論を無効化
make run-open                                # 補助 HTML を既定ブラウザで開く
make run-pdf                                 # 補助 PDF も生成（要 weasyprint）
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
