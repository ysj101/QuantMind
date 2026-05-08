# QuantMind Desktop IPC / RPC Contract

## Purpose

This document defines the boundary for the Electron desktop app described in #41 and #42.
The renderer never talks to DuckDB, Python modules, shell commands, or Codex app-server directly.
It calls a fixed preload API, the Electron main process maps that API to Python JSON-RPC over stdio,
and Python reuses the existing QuantMind CLI/pipeline/storage modules.

## Ownership Boundary

| Layer | Owns | Must not own |
| --- | --- | --- |
| Electron renderer | Desktop UI state, filtering controls, rendering summaries/transcripts | DuckDB access, shell execution, arbitrary filesystem access |
| Electron preload | Narrow `window.quantmind` API and type-safe argument validation | Business logic, DB queries, command execution |
| Electron main process | Window lifecycle, IPC handlers, Python RPC child process, optional Codex app-server adapter | Screening/debate logic, direct DB mutations outside RPC |
| Python desktop service | Read models, pipeline operations, schemas, error normalization | Browser UI hosting, Electron window control |
| Existing Python CLI/pipeline | `run_daily`, storage, report export, portfolio/report compatibility | Desktop IPC details |
| Codex app-server adapter | Optional Codex runtime/control connection from main process | QuantMind business HTTP endpoints or renderer host |

## Transport

- Renderer -> preload: `contextBridge.exposeInMainWorld("quantmind", api)`.
- Preload -> main: Electron `ipcRenderer.invoke(channel, payload)`.
- Main -> Python: newline-delimited JSON-RPC 2.0 over stdio.
- Python -> main: one JSON-RPC response per line.
- No localhost HTTP port is opened for the desktop data path.

## Shared Types

Dates use `YYYY-MM-DD`. Timestamps use ISO 8601 strings in local process timezone unless DuckDB
returns a date-only value.

```ts
export type PipelineStatus = "success" | "skipped" | "failed" | "running" | "missing";

export interface PipelineStep {
  name: string;
  status: PipelineStatus;
  detail: string;
  startedAt: string | null;
  finishedAt: string | null;
}

export interface PipelineRunSummary {
  date: string;
  latestStatus: PipelineStatus;
  startedAt: string | null;
  finishedAt: string | null;
  steps: PipelineStep[];
}

export interface ExtractedSymbol {
  date: string;
  code: string;
  rank: number | null;
  score: number | null;
  rulesHit: string[];
  recommendation: string | null;
  confidence: number | null;
  summary: string | null;
}

export interface DebateMessage {
  role: "bull" | "bear" | "judge" | string;
  model: string | null;
  prompt: string | null;
  output: string;
  confidence: number | null;
  durationSec: number | null;
  error: string | null;
  createdAt: string | null;
}

export interface DebateTranscript {
  date: string;
  code: string;
  conversationId: string | null;
  messages: DebateMessage[];
}

export interface RunDailyOptions {
  date: string;
  force?: boolean;
  discover?: boolean;
  llmDebate?: boolean;
  pdf?: boolean;
}

export interface RunDailyHandle {
  runId: string;
  status: PipelineStatus;
}
```

## Preload API

The renderer sees only this API:

```ts
interface QuantMindDesktopApi {
  listRuns(filters?: RunFilters): Promise<PipelineRunSummary[]>;
  getDailySummary(date: string): Promise<DailySummary>;
  listExtractedSymbols(date: string, filters?: SymbolFilters): Promise<ExtractedSymbol[]>;
  getSymbolDetail(date: string, code: string): Promise<SymbolDetail>;
  getDebateTranscript(date: string, code: string): Promise<DebateTranscript>;
  searchHistory(filters: HistoryFilters): Promise<ExtractedSymbol[]>;
  runDaily(options: RunDailyOptions): Promise<RunDailyHandle>;
  getRunStatus(runId: string): Promise<PipelineRunSummary>;
}
```

IPC channels are prefixed with `quantmind:` and match the API name, for example
`quantmind:listRuns` and `quantmind:runDaily`.

## Python JSON-RPC Methods

The Python service exposes methods with snake_case names. All responses conform to the shared types
above after the main/preload layer converts keys to camelCase.

| JSON-RPC method | Purpose | Mutates DB |
| --- | --- | --- |
| `desktop.list_runs` | Return historical pipeline run summaries, newest first | No |
| `desktop.get_daily_summary` | Return regime, latest steps, extracted symbol count, debate count | No |
| `desktop.list_extracted_symbols` | Return ranked symbols for a date with recommendation/confidence if available | No |
| `desktop.get_symbol_detail` | Return screening row, debate decision, scenarios, alerts for a symbol/date | No |
| `desktop.get_debate_transcript` | Return Bull/Bear/Judge messages grouped by conversation where possible | No |
| `desktop.search_history` | Filter historical extracted symbols by date/code/recommendation/confidence/status | No |
| `desktop.run_daily` | Start guarded daily pipeline execution | Yes |
| `desktop.get_run_status` | Return status for an in-process or persisted run | No |

## Request Examples

```json
{"jsonrpc":"2.0","id":"1","method":"desktop.list_runs","params":{"limit":30}}
{"jsonrpc":"2.0","id":"2","method":"desktop.get_daily_summary","params":{"date":"2026-05-05"}}
{"jsonrpc":"2.0","id":"3","method":"desktop.list_extracted_symbols","params":{"date":"2026-05-05","recommendation":"buy"}}
{"jsonrpc":"2.0","id":"4","method":"desktop.run_daily","params":{"date":"2026-05-05","force":true,"discover":false,"llm_debate":false,"pdf":false}}
```

## Error Shape

Python returns JSON-RPC error objects and the Electron main process maps them to rejected promises.

```json
{
  "code": -32001,
  "message": "not_found",
  "data": {
    "kind": "missing_date",
    "detail": "No pipeline data exists for 2026-05-05"
  }
}
```

Reserved application error kinds:

- `missing_date`
- `missing_symbol`
- `validation_error`
- `pipeline_running`
- `cli_missing`
- `pipeline_failed`
- `internal_error`

## Pipeline Operation Rules

- `desktop.run_daily` is guarded by a single in-process lock; a second call returns `pipeline_running`.
- `discover=false` maps to the existing `--no-discover` behavior at CLI/service boundary.
- `llm_debate=false` maps to the existing `--no-llm-debate` behavior and must not require Claude/Codex CLIs.
- `pdf=true` asks the existing report exporter for PDF output, preserving the current optional dependency behavior.
- Missing `claude` or `codex` binaries are returned as `cli_missing` when an LLM debate is requested.
- Read-only methods open DuckDB with read-only connections and must not write `pipeline_runs`.

## Implementation Notes

- #44 implements the read-model functions behind the read-only methods.
- #45 adds conversation grouping metadata while preserving best-effort reads of old `llm_decisions`.
- #46 wires read-only JSON-RPC methods and Electron IPC handlers.
- #47 wires the guarded `run_daily` operation.
- #48 builds the renderer around this preload API.
