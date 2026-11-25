import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { api, errorMessage } from "../api";
import type { Stats } from "../types";

export function UsageView({ databaseId, databaseName }: { databaseId: string; databaseName: string }) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setStats(null);
    setError(null);
    api
      .stats(databaseId)
      .then((s) => !cancelled && setStats(s))
      .catch((e) => !cancelled && setError(errorMessage(e)));
    return () => {
      cancelled = true;
    };
  }, [databaseId]);

  const peak = Math.max(1, ...(stats?.daily.map((d) => d.count) ?? [1]));

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Usage on {databaseName}</h1>
          <p className="muted">How the AI is doing on your questions, from your saved history.</p>
        </div>
      </header>
      {error && <div className="notice error">{error}</div>}
      {!stats && !error && (
        <p className="muted">
          <Loader2 size={14} className="spin" /> Loading…
        </p>
      )}
      {stats && stats.total === 0 && (
        <div className="empty-state">
          <h3>No questions yet</h3>
          <p className="muted">Ask something on the Ask page. Every question and query is counted here.</p>
        </div>
      )}
      {stats && stats.total > 0 && (
        <>
          <dl className="figures">
            <div>
              <dt>Questions and queries</dt>
              <dd>{stats.total}</dd>
            </div>
            <div>
              <dt>Ran without errors</dt>
              <dd>{stats.success_rate === null ? "–" : `${Math.round(stats.success_rate * 100)}%`}</dd>
            </div>
            <div>
              <dt>Fixed by the AI itself</dt>
              <dd>{stats.repaired}</dd>
            </div>
            <div>
              <dt>Average answer time</dt>
              <dd>{stats.avg_seconds === null ? "–" : `${stats.avg_seconds}s`}</dd>
            </div>
          </dl>

          <section className="usage-chart">
            <h2>Last 14 days</h2>
            <div className="bars" role="img" aria-label="Questions per day for the last 14 days">
              {stats.daily.map((d) => (
                <div key={d.day} className="bar-col" title={`${d.day}: ${d.count}`}>
                  <span className="bar-value">{d.count || ""}</span>
                  <span className="bar" style={{ height: `${(d.count / peak) * 100}%` }} />
                  <span className="bar-day">{d.day.slice(8)}</span>
                </div>
              ))}
            </div>
          </section>

          <section className="usage-split">
            <h2>How you asked</h2>
            <div className="split-bar" aria-hidden>
              <span style={{ flex: stats.ai }} className="ai" />
              <span style={{ flex: stats.manual }} className="manual" />
            </div>
            <p className="muted">
              {stats.ai} in plain English, {stats.manual} written as SQL, {stats.failed} failed.
            </p>
          </section>
        </>
      )}
    </div>
  );
}
