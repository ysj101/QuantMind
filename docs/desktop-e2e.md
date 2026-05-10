# Desktop E2E and Operations Checklist

This checklist verifies the Electron desktop app, Python JSON-RPC service, existing CLI/report path, and missing-CLI behavior.

## One-time Setup

```bash
make setup
make desktop-setup
make init-db
```

Use an isolated data directory for repeatable checks:

```bash
export QUANTMIND_DATA_DIR=/tmp/quantmind-desktop-e2e
rm -rf "$QUANTMIND_DATA_DIR"
make init-db
make desktop-demo-data DATE=2026-05-05
```

## Automated Checks

```bash
uv run pytest
pnpm -C apps/desktop test
make help
```

Coverage expected from the automated suite:

- read-only desktop RPC does not add `pipeline_runs`
- missing dates and symbols return stable empty responses
- guarded daily run API reports success and failed steps
- concurrent desktop runs return `pipeline_running`
- missing `claude` / `codex` binaries return `cli_missing`
- existing HTML/PDF report tests still pass

## Desktop UI Smoke

```bash
make desktop-start
```

In the Electron window:

1. Set the date to `2026-05-05`.
2. Confirm the summary shows `success`, `Extracted=1`, `Debates=1`, and `Regime=risk_on`.
3. Confirm the extracted symbol table shows code `1234`, rank `1`, decision `buy`, and rules `volume_spike, tdnet_today`.
4. Select `1234` and confirm the detail pane shows Bull, Bear, and Judge transcript entries.
5. Confirm the pipeline run timeline contains `2026-05-05`.
6. Toggle `LLM debate` on in an environment without `claude` or `codex`, run the panel, and confirm the run status reports `cli_missing`.

## Development Window

For renderer iteration:

```bash
make desktop-dev
```

In a second terminal:

```bash
make desktop-window
```

This still uses Electron as the UI host; Vite is only the renderer development server.

## Existing Report Path

HTML/PDF reports are auxiliary exports, not the primary UI:

```bash
make run DATE=2026-05-05 DISCOVER=--no-discover LLM_DEBATE=--no-llm-debate
make run-pdf DATE=2026-05-05 DISCOVER=--no-discover LLM_DEBATE=--no-llm-debate
make run-open DATE=2026-05-05 DISCOVER=--no-discover LLM_DEBATE=--no-llm-debate
```
