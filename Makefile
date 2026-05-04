# --------------------------------------------------------------------------
# QuantMind Makefile
#
# 環境変数で挙動を変えられます:
#   DATE=YYYY-MM-DD   日次系コマンドの対象日（既定: 本日）
#   OUT=path          レポート出力先
#   CODES="7203 6758" 銘柄コード一覧（スペース区切り）
#   START / END       バックテスト期間
#   REGISTRY=path     IR レジストリ YAML
#   TOP=10            スクリーニング Top N
# --------------------------------------------------------------------------

DATE     ?= $(shell date +%Y-%m-%d)
OUT      ?= reports
CODES    ?=
START    ?=
END      ?=
REGISTRY ?= src/quantmind/data/ir_docs/registry_sample.yaml
TOP      ?= 10

UV_RUN := uv run

.PHONY: help setup init-db info run run-pdf run-open backtest \
        prices tdnet edinet edinet-download ir universe screen \
        position-list position-history position-summary \
        lint format test typecheck check pre-commit clean

help:
	@echo "QuantMind make targets"
	@echo ""
	@echo "  セットアップ:"
	@echo "    make setup          uv sync --all-extras"
	@echo "    make init-db        DuckDB スキーマ初期化"
	@echo ""
	@echo "  日常運用:"
	@echo "    make info           バージョン確認"
	@echo "    make run            日次パイプライン → HTML レポート (DATE=)"
	@echo "    make run-pdf        日次パイプライン → HTML+PDF"
	@echo "    make run-open       日次パイプライン → HTML を既定ブラウザで開く"
	@echo "    make backtest       ルールベース戦略のバックテスト (START=, END=)"
	@echo ""
	@echo "  データ収集:"
	@echo "    make prices CODES='7203 6758' [START=YYYY-MM-DD END=YYYY-MM-DD]"
	@echo "    make tdnet  [DATE=YYYY-MM-DD]"
	@echo "    make edinet [DATE=YYYY-MM-DD]"
	@echo "    make edinet-download DOC_ID=Sxxxx [KIND=xbrl|pdf]"
	@echo "    make ir     [REGISTRY=path/to/registry.yaml] [CODES='1234 5678']"
	@echo ""
	@echo "  分析・運用:"
	@echo "    make universe [DATE=YYYY-MM-DD]"
	@echo "    make screen   [DATE=YYYY-MM-DD] [TOP=10]"
	@echo "    make position-list / position-history / position-summary"
	@echo ""
	@echo "  開発:"
	@echo "    make lint format typecheck test check pre-commit clean"

# --- セットアップ -----------------------------------------------------------
setup:
	uv sync --all-extras

init-db:
	$(UV_RUN) python -m quantmind.storage init

# --- 日常運用 ---------------------------------------------------------------
info:
	$(UV_RUN) quantmind info

run:
	$(UV_RUN) quantmind run --date $(DATE) --out $(OUT)

run-pdf:
	$(UV_RUN) quantmind run --date $(DATE) --out $(OUT) --pdf

run-open:
	$(UV_RUN) quantmind run --date $(DATE) --out $(OUT) --open

backtest:
	@if [ -z "$(START)" ] || [ -z "$(END)" ]; then \
		echo "usage: make backtest START=YYYY-MM-DD END=YYYY-MM-DD [OUT=reports/backtest.html]"; \
		exit 2; \
	fi
	$(UV_RUN) quantmind backtest --start $(START) --end $(END) --out $(OUT)/backtest.html

# --- データ収集 -------------------------------------------------------------
prices:
	@if [ -z "$(CODES)" ]; then \
		echo "usage: make prices CODES='7203 6758' [START=YYYY-MM-DD] [END=YYYY-MM-DD]"; \
		exit 2; \
	fi
	$(UV_RUN) python -m quantmind.data.prices update --codes $(CODES) \
		$(if $(START),--start $(START)) $(if $(END),--end $(END))

tdnet:
	$(UV_RUN) python -m quantmind.data.tdnet fetch --date $(DATE)

edinet:
	$(UV_RUN) python -m quantmind.data.edinet list --date $(DATE)

edinet-download:
	@if [ -z "$(DOC_ID)" ]; then \
		echo "usage: make edinet-download DOC_ID=Sxxxx [KIND=xbrl|pdf]"; \
		exit 2; \
	fi
	$(UV_RUN) python -m quantmind.data.edinet download $(DOC_ID) --kind $(or $(KIND),xbrl)

ir:
	$(UV_RUN) python -m quantmind.data.ir_docs collect --registry $(REGISTRY) \
		$(if $(CODES),--codes $(CODES))

# --- 分析・運用 -------------------------------------------------------------
universe:
	$(UV_RUN) python -m quantmind.universe build --date $(DATE)

screen:
	$(UV_RUN) python -m quantmind.screening run --date $(DATE) --top $(TOP)

position-list:
	$(UV_RUN) python -m quantmind.portfolio list

position-history:
	$(UV_RUN) python -m quantmind.portfolio history

position-summary:
	$(UV_RUN) python -m quantmind.portfolio summary

# --- 開発 -------------------------------------------------------------------
lint:
	$(UV_RUN) ruff check .

format:
	$(UV_RUN) ruff format .
	$(UV_RUN) ruff check --fix .

typecheck:
	$(UV_RUN) mypy src

test:
	$(UV_RUN) pytest

check: lint typecheck test

pre-commit:
	$(UV_RUN) pre-commit run --all-files

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +
