export type PipelineStatus = "success" | "skipped" | "failed" | "running" | "missing" | string;

export interface PipelineStep {
  name: string;
  status: PipelineStatus;
  detail: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface PipelineRunSummary {
  date: string;
  latest_status: PipelineStatus;
  started_at: string | null;
  finished_at: string | null;
  steps: PipelineStep[];
}

export interface DailySummary {
  date: string;
  latest_status: PipelineStatus;
  steps: PipelineStep[];
  extracted_count: number;
  debate_count: number;
  regime: { regime?: string; score?: number; components?: Record<string, unknown> } | null;
}

export interface ExtractedSymbol {
  date: string;
  code: string;
  rank: number | null;
  score: number | null;
  rules_hit: string[];
  recommendation: string | null;
  confidence: number | null;
  summary: string | null;
}

export interface DebateMessage {
  role: string;
  model: string | null;
  system_prompt: string | null;
  prompt: string | null;
  output: string;
  confidence: number | null;
  duration_sec: number | null;
  error: string | null;
  created_at: string | null;
}

export interface DebateTranscript {
  date: string;
  code: string;
  conversation_id: string | null;
  messages: DebateMessage[];
}

export interface SymbolDetail {
  date: string;
  code: string;
  extracted: ExtractedSymbol | null;
  debate: DebateTranscript;
  scenarios: Array<Record<string, unknown>>;
  alerts: Array<Record<string, unknown>>;
}

export interface RunDailyOptions {
  date: string;
  force?: boolean;
  discover?: boolean;
  discoverLimit?: number;
  priceLookbackDays?: number;
  llmDebate?: boolean;
  pdf?: boolean;
  outDir?: string;
}

export interface RunDailyHandle {
  run_id: string;
  date: string;
  status: PipelineStatus;
}

export interface RunDailyStatus extends RunDailyHandle {
  detail: string;
  started_at: string | null;
  finished_at: string | null;
  steps: PipelineStep[];
  report_html: string | null;
  report_pdf: string | null;
}

export interface QuantMindApi {
  listRuns(filters?: { limit?: number }): Promise<PipelineRunSummary[]>;
  getDailySummary(date: string): Promise<DailySummary>;
  listExtractedSymbols(
    date: string,
    filters?: { code?: string; recommendation?: string; min_confidence?: number },
  ): Promise<ExtractedSymbol[]>;
  getSymbolDetail(date: string, code: string): Promise<SymbolDetail>;
  getDebateTranscript(date: string, code: string): Promise<DebateTranscript>;
  searchHistory(filters: Record<string, unknown>): Promise<ExtractedSymbol[]>;
  runDaily(options: RunDailyOptions): Promise<RunDailyHandle>;
  getRunStatus(runId: string): Promise<RunDailyStatus>;
}

declare global {
  interface Window {
    quantmind: QuantMindApi;
  }
}
