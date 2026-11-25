import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowRightLeft,
  BarChart3,
  Check,
  ChevronDown,
  ChevronRight,
  ClipboardList,
  Copy,
  Download,
  EyeOff,
  GraduationCap,
  ThumbsUp,
  Info,
  Loader2,
  Pin,
  PinOff,
  Play,
  Table2,
  Wrench,
} from "lucide-react";
import { inferChart } from "../lib/chart";
import { api, errorMessage } from "../api";
import { downloadText, formatDuration, toCsv, toMarkdown } from "../lib/format";
import type { ExplainResponse, Schema, Theme, Turn } from "../types";
import { ResultChart } from "./ResultChart";
import { ResultsTable } from "./ResultsTable";
import { SqlEditor } from "./SqlEditor";

interface Props {
  turn: Turn;
  schema: Schema | null;
  dialect: string;
  theme: Theme;
  onRun: (turn: Turn, sql: string) => void;
  dbName: (id: string) => string;
  onSwitchDb: (turn: Turn) => void;
  onAsk: (question: string) => void;
  pinned: boolean;
  onPin: (turn: Turn) => void;
  canAsk: boolean;
  llmEnabled: boolean;
  /** Present when this user may teach the app (analysts and admins). */
  onTeach?: (turn: Turn, sql: string) => Promise<void>;
}

export function TurnCard({ turn, schema, dialect, theme, onRun, dbName, onSwitchDb, onAsk, pinned, onPin, canAsk, llmEnabled, onTeach }: Props) {
  const [sql, setSql] = useState(turn.sql);
  const [view, setView] = useState<"table" | "chart">("table");
  const [copied, setCopied] = useState(false);
  const [mdCopied, setMdCopied] = useState(false);
  const [taught, setTaught] = useState(false);
  const [explain, setExplain] = useState<{ loading: boolean; data?: ExplainResponse; error?: string } | null>(null);
  const [showAttempts, setShowAttempts] = useState(false);
  // null = automatic: show the SQL, except when a plain-language answer is already there to read first.
  const [sqlOpen, setSqlOpen] = useState<boolean | null>(null);
  const showSql = sqlOpen ?? (!turn.summary || turn.mode === "sql");

  // Take the SQL from the server when it arrives, but don't overwrite the user's text
  // when the server only normalised it (e.g. stripped a trailing semicolon).
  useEffect(() => {
    const norm = (s: string) => s.trim().replace(/;+$/, "").trim();
    setSql((current) => (norm(current) === norm(turn.sql) ? current : turn.sql));
  }, [turn.sql]);

  const chart = useMemo(() => (turn.result ? inferChart(turn.result) : null), [turn.result]);
  useEffect(() => {
    if (!chart) setView("table");
  }, [chart]);

  const busy = turn.status !== "done";
  const edited = sql.trim() !== turn.sql.trim();

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked */
    }
  };

  const copyMarkdown = async () => {
    if (!turn.result) return;
    try {
      await navigator.clipboard.writeText(toMarkdown(turn.result));
      setMdCopied(true);
      setTimeout(() => setMdCopied(false), 1500);
    } catch {
      /* clipboard blocked */
    }
  };

  const explainSql = async () => {
    if (explain?.data || explain?.loading) return setExplain(explain.data ? null : explain);
    setExplain({ loading: true });
    try {
      const data = await api.explain({ database_id: turn.queryDb ?? turn.databaseId, sql });
      setExplain({ loading: false, data });
    } catch (e) {
      setExplain({ loading: false, error: errorMessage(e) });
    }
  };

  const teachThis = async () => {
    if (!onTeach) return;
    try {
      await onTeach(turn, sql);
      setTaught(true);
    } catch {
      /* the page already showed the reason */
    }
  };

  const run = () => {
    if (sql.trim() && !busy) onRun(turn, sql);
  };

  return (
    <article className="turn">
      {turn.question && <h2 className="turn-question">{turn.question}</h2>}

      <div className="turn-answer">
        <div className="turn-body">
          {turn.status === "thinking" && (
            <div className="thinking" role="status">
              <ol className="steps">
                {(turn.steps?.length ? turn.steps : ["Starting"]).map((s, i, all) => (
                  <li key={s + i} className={i === all.length - 1 ? "now" : "past"}>
                    {i === all.length - 1 ? <Loader2 size={13} className="spin" /> : <Check size={13} />} {s}
                  </li>
                ))}
              </ol>
            </div>
          )}

          {turn.status !== "thinking" && turn.answerable === false && (
            <div className="notice info">
              <Info size={16} />
              <div>
                <strong>This question can't be answered from this database.</strong>
                {turn.explanation && <p>{turn.explanation}</p>}
              </div>
            </div>
          )}

          {turn.status !== "thinking" && turn.answerable !== false && (
            <>
              {turn.routedFrom && turn.queryDb && (
                <div className="notice routed">
                  <ArrowRightLeft size={15} />
                  <span>
                    Answered from <strong>{dbName(turn.queryDb)}</strong>, because {dbName(turn.routedFrom)} doesn't have
                    this data.
                  </span>
                  <button className="ghost-btn" onClick={() => onSwitchDb(turn)}>
                    Switch to {dbName(turn.queryDb)}
                  </button>
                </div>
              )}
              {turn.summary && (
                <div className="insight">
                  <p>{turn.summary}</p>
                </div>
              )}
              {turn.explanation && <p className="explanation">{turn.explanation}</p>}

              {(turn.sql || turn.mode === "sql") && (
                <div className="sql-block">
                  <div className="sql-block-header">
                    <button className="link-btn sql-toggle" onClick={() => setSqlOpen(!showSql)} aria-expanded={showSql}>
                      {showSql ? <ChevronDown size={14} /> : <ChevronRight size={14} />} SQL{edited ? " (edited)" : ""}
                    </button>
                    <div className="actions">
                      <button
                        className={"ghost-btn" + (explain?.data ? " active" : "")}
                        onClick={explainSql}
                        disabled={!llmEnabled || !sql.trim()}
                        title={llmEnabled ? "Explain this query in plain words" : "Add an API key to use explanations"}
                      >
                        {explain?.loading ? <Loader2 size={14} className="spin" /> : <GraduationCap size={14} />} Explain
                      </button>
                      <button className="ghost-btn" onClick={copy} title="Copy SQL">
                        {copied ? <Check size={14} /> : <Copy size={14} />} {copied ? "Copied" : "Copy"}
                      </button>
                      <button className="primary-btn small" onClick={run} disabled={busy || !sql.trim()} title="Run (Ctrl+Enter)">
                        {turn.status === "running" ? <Loader2 size={14} className="spin" /> : <Play size={14} />} Run
                      </button>
                    </div>
                  </div>
                  {showSql && <SqlEditor value={sql} onChange={setSql} onRun={run} dialect={dialect} schema={schema} theme={theme} />}
                </div>
              )}

              {explain && !explain.loading && (
                <div className="explain">
                  {explain.error ? (
                    <p className="error-text">{explain.error}</p>
                  ) : (
                    explain.data && (
                      <>
                        <p>{explain.data.summary}</p>
                        <ol>
                          {explain.data.steps.map((st, i) => (
                            <li key={i}>{st}</li>
                          ))}
                        </ol>
                      </>
                    )
                  )}
                </div>
              )}

              {turn.attempts && turn.attempts.length > 0 && (
                <div className="notice subtle">
                  <Wrench size={14} />
                  <div>
                    <button className="link-btn" onClick={() => setShowAttempts((s) => !s)}>
                      Fixed {turn.attempts.length} error{turn.attempts.length > 1 ? "s" : ""} automatically
                      {showAttempts ? " (hide)" : " (show)"}
                    </button>
                    {showAttempts &&
                      turn.attempts.map((a, i) => (
                        <div key={i} className="attempt">
                          <pre>{a.sql}</pre>
                          <span className="error-text">{a.error}</span>
                        </div>
                      ))}
                  </div>
                </div>
              )}

              {turn.error && (
                <div className="notice error" role="alert">
                  <AlertTriangle size={16} />
                  <div>
                    <strong>{turn.result === undefined && !turn.sql ? "Something went wrong" : "The query failed"}</strong>
                    <p>{turn.error}</p>
                  </div>
                </div>
              )}

              {turn.result && (
                <div className={"result" + (turn.status === "running" ? " stale" : "")}>
                  <div className="result-toolbar">
                    <div className="segmented small" role="tablist" aria-label="Result view">
                      <button role="tab" aria-selected={view === "table"} className={view === "table" ? "active" : ""} onClick={() => setView("table")}>
                        <Table2 size={14} /> Table
                      </button>
                      <button
                        role="tab"
                        aria-selected={view === "chart"}
                        className={view === "chart" ? "active" : ""}
                        onClick={() => setView("chart")}
                        disabled={!chart}
                        title={chart ? "Show as chart" : "This result has no numeric column to chart"}
                      >
                        <BarChart3 size={14} /> Chart
                      </button>
                    </div>
                    {turn.result.masked_columns && turn.result.masked_columns.length > 0 && (
                      <span className="tag" title="Values in these columns look like personal data, so they are hidden. Set MASK_PII=false in .env to show them.">
                        <EyeOff size={12} /> hidden: {turn.result.masked_columns.join(", ")}
                      </span>
                    )}
                    <span className="meta">
                      {turn.result.row_count.toLocaleString()} row{turn.result.row_count === 1 ? "" : "s"}
                      {turn.result.truncated && " (limit reached)"} · {formatDuration(turn.result.elapsed_ms)}
                    </span>
                    {turn.usedMemory ? (
                      <span className="tag" title="Rules and confirmed examples from the Training page were added to the prompt">
                        <GraduationCap size={12} /> used {turn.usedMemory} from training
                      </span>
                    ) : null}
                    {onTeach && turn.question && !turn.error && !edited && (
                      <button
                        className={"ghost-btn" + (taught ? " active" : "")}
                        onClick={teachThis}
                        disabled={taught}
                        title="Confirm this answer is right so similar questions reuse its SQL"
                      >
                        {taught ? <Check size={14} /> : <ThumbsUp size={14} />} {taught ? "Taught" : "Teach"}
                      </button>
                    )}
                    {turn.historyId != null && (
                      <button
                        className={"ghost-btn" + (pinned ? " active" : "")}
                        onClick={() => onPin(turn)}
                        title={pinned ? "Remove from your dashboard" : "Pin to your dashboard"}
                      >
                        {pinned ? <PinOff size={14} /> : <Pin size={14} />} {pinned ? "Unpin" : "Pin"}
                      </button>
                    )}
                    <button className="ghost-btn" onClick={copyMarkdown} disabled={turn.result.row_count === 0} title="Copy as a Markdown table">
                      {mdCopied ? <Check size={14} /> : <ClipboardList size={14} />} {mdCopied ? "Copied" : "Markdown"}
                    </button>
                    <button
                      className="ghost-btn"
                      onClick={() => downloadText(`query-${turn.id.slice(0, 8)}.csv`, toCsv(turn.result!))}
                      disabled={turn.result.row_count === 0}
                      title="Download as CSV"
                    >
                      <Download size={14} /> CSV
                    </button>
                  </div>
                  {turn.result.truncated && (
                    <p className="hint">
                      Only the first {turn.result.row_count.toLocaleString()} rows are shown. Add filters or a LIMIT to narrow
                      the result.
                    </p>
                  )}
                  {view === "chart" && chart ? (
                    <ResultChart key={turn.result.elapsed_ms} spec={chart} theme={theme} />
                  ) : (
                    <ResultsTable result={turn.result} />
                  )}
                </div>
              )}

              {turn.followups && turn.followups.length > 0 && (
                <div className="followups">
                  <span className="label">Ask next</span>
                  <div className="chips">
                    {turn.followups.map((q) => (
                      <button key={q} className="chip" onClick={() => onAsk(q)} disabled={!canAsk}>
                        {q}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </article>
  );
}
