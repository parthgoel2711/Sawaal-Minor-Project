import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, Loader2, Pin, PinOff, RefreshCw, Wand2, X } from "lucide-react";
import { api, errorMessage } from "../api";
import { inferChart } from "../lib/chart";
import type { AutoDashboard, AutoWidget, ExecuteResponse, HistoryItem, Theme } from "../types";
import { ResultChart } from "./ResultChart";
import { ResultsTable } from "./ResultsTable";

interface Props {
  databaseId: string;
  databaseName: string;
  theme: Theme;
  onChanged: () => void;
  onBack: () => void;
}

type Loaded = { item: HistoryItem; run?: ExecuteResponse; failed?: string };

/** Pinned (starred) queries, re-run live so the numbers are always current. */
export function Dashboard({ databaseId, databaseName, theme, onChanged, onBack }: Props) {
  const [cards, setCards] = useState<Loaded[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [suggested, setSuggested] = useState<AutoDashboard | null>(null);
  const [suggesting, setSuggesting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const items = await api.history(databaseId, true);
      const runs = await Promise.all(
        items.map(async (item): Promise<Loaded> => {
          try {
            return { item, run: await api.execute({ database_id: databaseId, sql: item.sql, save_to_history: false }) };
          } catch (e) {
            return { item, failed: errorMessage(e) };
          }
        }),
      );
      setCards(runs);
      setUpdated(new Date());
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }, [databaseId]);

  useEffect(() => {
    load();
  }, [load]);

  const unpin = async (item: HistoryItem) => {
    try {
      await api.starHistory(item.id, false);
      setCards((c) => c && c.filter((x) => x.item.id !== item.id));
      onChanged();
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  const suggest = async () => {
    setSuggesting(true);
    setError(null);
    try {
      setSuggested(await api.autoDashboard(databaseId));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSuggesting(false);
    }
  };

  const pinWidgets = async (widgets: AutoWidget[]) => {
    try {
      for (const w of widgets) {
        const saved = await api.execute({ database_id: databaseId, sql: w.sql, question: w.title, save_to_history: true });
        if (saved.history_id != null) await api.starHistory(saved.history_id, true);
      }
      setSuggested((cur) => {
        if (!cur) return cur;
        const left = cur.widgets.filter((w) => !widgets.includes(w));
        return left.length ? { ...cur, widgets: left } : null;
      });
      onChanged();
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>{databaseName} dashboard</h1>
          <p className="muted">
            {updated ? `Pinned answers, re-run at ${updated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}.` : "Loading…"}
          </p>
        </div>
        <div className="page-actions">
          <button className="ghost-btn" onClick={suggest} disabled={suggesting}>
            {suggesting ? <Loader2 size={14} className="spin" /> : <Wand2 size={14} />} Suggest charts
          </button>
          <button className="ghost-btn" onClick={load} disabled={loading}>
            {loading ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />} Refresh
          </button>
        </div>
      </header>

      {error && (
        <div className="notice error" role="alert">
          <div>{error}</div>
        </div>
      )}

      {suggested && (
        <section className="suggest">
          <header className="suggest-head">
            <div>
              <h2>Suggested charts</h2>
              <p className="muted small">
                {suggested.source === "ai" ? "Proposed by the AI from your tables." : "Built from your column types."} Pin the ones
                you want to keep.
              </p>
            </div>
            <div className="page-actions">
              <button className="primary-btn small" onClick={() => pinWidgets(suggested.widgets)}>
                <Pin size={13} /> Pin all
              </button>
              <button className="icon-btn" onClick={() => setSuggested(null)} aria-label="Dismiss suggestions" title="Dismiss">
                <X size={15} />
              </button>
            </div>
          </header>
          {suggested.widgets.length === 0 && <p className="muted">No charts could be built for this database.</p>}
          <div className="dashboard-grid">
            {suggested.widgets.map((w) => (
              <SuggestedCard key={w.sql} widget={w} theme={theme} onPin={() => pinWidgets([w])} />
            ))}
          </div>
        </section>
      )}

      {cards && cards.length === 0 && !suggested && (
        <div className="empty-state">
          <h3>Nothing pinned yet</h3>
          <p className="muted">
            Ask a question, then press <strong>Pin</strong> on the answer. Pinned answers show up here and are re-run
            every time you open or refresh this page.
          </p>
          <div className="page-actions">
            <button className="primary-btn" onClick={suggest} disabled={suggesting}>
              <Wand2 size={14} /> Suggest charts
            </button>
            <button className="ghost-btn" onClick={onBack}>
              <ArrowLeft size={14} /> Go ask a question
            </button>
          </div>
        </div>
      )}

      <div className="dashboard-grid">
        {cards?.map((c) => (
          <DashboardCard key={c.item.id} card={c} theme={theme} onUnpin={() => unpin(c.item)} />
        ))}
      </div>
    </div>
  );
}

function DashboardCard({ card, theme, onUnpin }: { card: Loaded; theme: Theme; onUnpin: () => void }) {
  const { item, run, failed } = card;
  const result = run?.result ?? null;
  const chart = useMemo(() => (result ? inferChart(result) : null), [result]);
  const problem = failed ?? run?.error;
  return (
    <section className="dash-card">
      <header>
        <h3 title={item.sql}>{item.question ?? item.sql.slice(0, 80)}</h3>
        <button className="icon-btn" onClick={onUnpin} title="Remove from dashboard" aria-label="Remove from dashboard">
          <PinOff size={14} />
        </button>
      </header>
      {item.explanation && <p className="muted small">{item.explanation}</p>}
      {problem && <p className="error-text">{problem}</p>}
      {result && (chart ? <ResultChart spec={chart} theme={theme} /> : <ResultsTable result={result} />)}
    </section>
  );
}

function SuggestedCard({ widget, theme, onPin }: { widget: AutoWidget; theme: Theme; onPin: () => void }) {
  const chart = useMemo(() => inferChart(widget.result), [widget.result]);
  return (
    <section className="dash-card">
      <header>
        <h3 title={widget.sql}>{widget.title}</h3>
        <button className="ghost-btn" onClick={onPin} title="Pin to your dashboard">
          <Pin size={13} /> Pin
        </button>
      </header>
      {widget.note && <p className="muted small">{widget.note}</p>}
      {chart ? <ResultChart spec={chart} theme={theme} /> : <ResultsTable result={widget.result} />}
    </section>
  );
}
