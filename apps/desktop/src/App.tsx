import {
  Activity,
  AlertTriangle,
  CalendarDays,
  CheckCircle2,
  CircleDot,
  History,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  SkipForward,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type {
  DailySummary,
  ExtractedSymbol,
  PipelineRunSummary,
  RunDailyStatus,
  SymbolDetail,
} from "./api";

const today = new Date().toISOString().slice(0, 10);

function statusIcon(status: string) {
  if (status === "success") return <CheckCircle2 size={16} />;
  if (status === "failed") return <XCircle size={16} />;
  if (status === "skipped") return <SkipForward size={16} />;
  if (status === "running") return <RefreshCw size={16} className="spin" />;
  return <CircleDot size={16} />;
}

function formatNumber(value: number | null | undefined, digits = 2) {
  return value == null ? "-" : value.toFixed(digits);
}

export default function App() {
  const [date, setDate] = useState(today);
  const [codeQuery, setCodeQuery] = useState("");
  const [recommendation, setRecommendation] = useState("");
  const [summary, setSummary] = useState<DailySummary | null>(null);
  const [symbols, setSymbols] = useState<ExtractedSymbol[]>([]);
  const [runs, setRuns] = useState<PipelineRunSummary[]>([]);
  const [selectedCode, setSelectedCode] = useState<string>("");
  const [detail, setDetail] = useState<SymbolDetail | null>(null);
  const [activeRun, setActiveRun] = useState<RunDailyStatus | null>(null);
  const [force, setForce] = useState(false);
  const [discover, setDiscover] = useState(false);
  const [llmDebate, setLlmDebate] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const filteredSymbols = useMemo(() => {
    return symbols.filter((symbol) => {
      if (codeQuery && !symbol.code.includes(codeQuery)) return false;
      if (recommendation && symbol.recommendation !== recommendation) return false;
      return true;
    });
  }, [symbols, codeQuery, recommendation]);

  async function refresh(targetDate = date) {
    setLoading(true);
    setError(null);
    try {
      const [nextRuns, nextSummary, nextSymbols] = await Promise.all([
        window.quantmind.listRuns({ limit: 18 }),
        window.quantmind.getDailySummary(targetDate),
        window.quantmind.listExtractedSymbols(targetDate),
      ]);
      setRuns(nextRuns);
      setSummary(nextSummary);
      setSymbols(nextSymbols);
      const fallbackCode = nextSymbols[0]?.code ?? "";
      setSelectedCode((current) => current || fallbackCode);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh(date);
  }, [date]);

  useEffect(() => {
    if (!selectedCode) {
      setDetail(null);
      return;
    }
    window.quantmind
      .getSymbolDetail(date, selectedCode)
      .then(setDetail)
      .catch((nextError) => setError(nextError instanceof Error ? nextError.message : String(nextError)));
  }, [date, selectedCode]);

  useEffect(() => {
    if (!activeRun || activeRun.status !== "running") return;
    const timer = window.setInterval(async () => {
      const status = await window.quantmind.getRunStatus(activeRun.run_id);
      setActiveRun(status);
      if (status.status !== "running") {
        window.clearInterval(timer);
        void refresh(date);
      }
    }, 1200);
    return () => window.clearInterval(timer);
  }, [activeRun, date]);

  async function startDailyRun() {
    setError(null);
    const handle = await window.quantmind.runDaily({
      date,
      force,
      discover,
      llmDebate,
      pdf: false,
    });
    setActiveRun({ ...handle, detail: "", started_at: null, finished_at: null, steps: [], report_html: null, report_pdf: null });
  }

  return (
    <main className="shell">
      <aside className="rail">
        <div className="brand">
          <ShieldCheck size={30} />
          <div>
            <strong>QuantMind</strong>
            <span>Desktop</span>
          </div>
        </div>
        <nav>
          <a className="active"><Activity size={17} /> Daily</a>
          <a><History size={17} /> History</a>
          <a><AlertTriangle size={17} /> Alerts</a>
        </nav>
        <div className="runbox">
          <div className="runbox-title">
            <Play size={16} />
            Daily Run
          </div>
          <label><input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} /> force</label>
          <label><input type="checkbox" checked={discover} onChange={(e) => setDiscover(e.target.checked)} /> discover</label>
          <label><input type="checkbox" checked={llmDebate} onChange={(e) => setLlmDebate(e.target.checked)} /> LLM debate</label>
          <button className="primary" onClick={startDailyRun} disabled={activeRun?.status === "running"}>
            <Play size={16} /> Run
          </button>
          {activeRun && (
            <div className={`run-status ${activeRun.status}`}>
              {statusIcon(activeRun.status)}
              <span>{activeRun.status}</span>
            </div>
          )}
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h1>日次パイプライン</h1>
            <p>抽出銘柄、根拠、Bull/Bear/Judge 議論を Electron window で確認</p>
          </div>
          <div className="toolbar">
            <label className="date-control">
              <CalendarDays size={16} />
              <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            </label>
            <button onClick={() => refresh()}><RefreshCw size={16} className={loading ? "spin" : ""} /> Refresh</button>
          </div>
        </header>

        {error && <div className="error"><AlertTriangle size={16} /> {error}</div>}

        <section className="metrics">
          <div>
            <span>Status</span>
            <strong className={`status-pill ${summary?.latest_status || "missing"}`}>
              {statusIcon(summary?.latest_status || "missing")}
              {summary?.latest_status || "missing"}
            </strong>
          </div>
          <div>
            <span>Extracted</span>
            <strong>{summary?.extracted_count ?? 0}</strong>
          </div>
          <div>
            <span>Debates</span>
            <strong>{summary?.debate_count ?? 0}</strong>
          </div>
          <div>
            <span>Regime</span>
            <strong>{summary?.regime?.regime ?? "-"}</strong>
          </div>
        </section>

        <section className="content-grid">
          <section className="panel symbols-panel">
            <div className="panel-heading">
              <h2>抽出銘柄</h2>
              <div className="filters">
                <label><Search size={14} /><input value={codeQuery} onChange={(e) => setCodeQuery(e.target.value)} placeholder="code" /></label>
                <select value={recommendation} onChange={(e) => setRecommendation(e.target.value)}>
                  <option value="">all</option>
                  <option value="buy">buy</option>
                  <option value="watch">watch</option>
                  <option value="skip">skip</option>
                </select>
              </div>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>Rank</th><th>Code</th><th>Score</th><th>Decision</th><th>Rules</th></tr>
                </thead>
                <tbody>
                  {filteredSymbols.map((symbol) => (
                    <tr key={symbol.code} className={selectedCode === symbol.code ? "selected" : ""} onClick={() => setSelectedCode(symbol.code)}>
                      <td>{symbol.rank ?? "-"}</td>
                      <td className="code">{symbol.code}</td>
                      <td>{formatNumber(symbol.score)}</td>
                      <td><span className={`decision ${symbol.recommendation || "none"}`}>{symbol.recommendation || "-"}</span></td>
                      <td>{symbol.rules_hit.join(", ") || "-"}</td>
                    </tr>
                  ))}
                  {!filteredSymbols.length && (
                    <tr><td colSpan={5} className="empty">No extracted symbols for this date</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel detail-panel">
            <div className="panel-heading">
              <h2>銘柄詳細 {selectedCode && <span>{selectedCode}</span>}</h2>
            </div>
            {detail?.extracted ? (
              <div className="detail-stack">
                <div className="summary-line">
                  <strong>{detail.extracted.summary || "No summary"}</strong>
                  <span>confidence {formatNumber(detail.extracted.confidence)}</span>
                </div>
                <div className="transcript">
                  {detail.debate.messages.map((message) => (
                    <article key={`${message.role}-${message.created_at}`} className={`message ${message.role}`}>
                      <header>
                        <strong>{message.role}</strong>
                        <span>{message.model || "-"}</span>
                      </header>
                      {message.error ? <p className="message-error">{message.error}</p> : <p>{message.output || "-"}</p>}
                    </article>
                  ))}
                  {!detail.debate.messages.length && <div className="empty">No debate transcript</div>}
                </div>
                <div className="risk-strip">
                  <div><strong>{detail.scenarios.length}</strong><span>scenarios</span></div>
                  <div><strong>{detail.alerts.length}</strong><span>alerts</span></div>
                </div>
              </div>
            ) : (
              <div className="empty detail-empty">Select a symbol to inspect the debate trail</div>
            )}
          </section>
        </section>

        <section className="panel history-panel">
          <div className="panel-heading"><h2>Pipeline runs</h2></div>
          <div className="run-timeline">
            {runs.map((run) => (
              <button key={run.date} className={run.date === date ? "current" : ""} onClick={() => setDate(run.date)}>
                <span>{run.date}</span>
                <em className={run.latest_status}>{statusIcon(run.latest_status)}{run.latest_status}</em>
              </button>
            ))}
            {!runs.length && <div className="empty">No pipeline runs recorded</div>}
          </div>
        </section>
      </section>
    </main>
  );
}
