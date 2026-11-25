import { useCallback, useEffect, useState } from "react";
import { BookMarked, Loader2, Plus, Trash2 } from "lucide-react";
import { api, errorMessage } from "../api";
import type { MemoryItem } from "../types";

interface Props {
  databaseId: string;
  databaseName: string;
  canEdit: boolean;
  onNotify: (message: string, kind?: "error") => void;
}

/** What the app has been taught about this database. Everything here is added to the AI's prompt when it is relevant. */
export function TrainingView({ databaseId, databaseName, canEdit, onNotify }: Props) {
  const [items, setItems] = useState<MemoryItem[] | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setItems(await api.memory(databaseId));
    } catch (e) {
      onNotify(errorMessage(e), "error");
      setItems([]);
    }
  }, [databaseId, onNotify]);

  useEffect(() => {
    load();
  }, [load]);

  const addNote = async () => {
    if (note.trim().length < 3) return;
    setBusy(true);
    try {
      await api.teachNote(databaseId, note.trim());
      setNote("");
      load();
    } catch (e) {
      onNotify(errorMessage(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const forget = async (id: number) => {
    try {
      await api.forget(id);
      setItems((all) => all && all.filter((i) => i.id !== id));
    } catch (e) {
      onNotify(errorMessage(e), "error");
    }
  };

  const notes = items?.filter((i) => i.kind === "note") ?? [];
  const examples = items?.filter((i) => i.kind === "example") ?? [];

  return (
    <div className="page training">
      <header className="page-head">
        <div>
          <h1>Training for {databaseName}</h1>
          <p className="muted">
            What you teach here is added to the AI's instructions on this database, so later answers follow your rules
            and your own SQL. Nothing leaves this server except the questions you ask.
          </p>
        </div>
      </header>

      <section className="train-section">
        <h2>Rules and definitions</h2>
        <p className="muted small">Plain sentences the AI must follow, such as how a figure is calculated or what a word means here.</p>
        {canEdit && (
          <div className="note-form">
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={2}
              maxLength={1000}
              placeholder="An active customer is one who placed an order in the last 90 days"
              aria-label="New rule"
            />
            <button className="primary-btn" onClick={addNote} disabled={busy || note.trim().length < 3}>
              {busy ? <Loader2 size={14} className="spin" /> : <Plus size={14} />} Add rule
            </button>
          </div>
        )}
        {items === null && <p className="muted small">Loading</p>}
        {items && notes.length === 0 && <p className="muted small">No rules yet.</p>}
        <ul className="train-list">
          {notes.map((n) => (
            <li key={n.id}>
              <BookMarked size={15} />
              <div>
                <p>{n.text}</p>
                <span className="train-meta">
                  {n.created_by} · used {n.uses} {n.uses === 1 ? "time" : "times"}
                </span>
              </div>
              {canEdit && (
                <button className="icon-btn" onClick={() => forget(n.id)} aria-label="Forget this rule" title="Forget">
                  <Trash2 size={14} />
                </button>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section className="train-section">
        <h2>Answers you confirmed</h2>
        <p className="muted small">
          Press <strong>Teach</strong> under an answer that is right. Similar questions will then be shown this SQL as an example.
        </p>
        {items && examples.length === 0 && <p className="muted small">Nothing confirmed yet.</p>}
        <ul className="train-list">
          {examples.map((e) => (
            <li key={e.id}>
              <div className="train-example">
                <p>{e.question}</p>
                <pre>{e.sql}</pre>
                <span className="train-meta">
                  {e.created_by} · used {e.uses} {e.uses === 1 ? "time" : "times"}
                </span>
              </div>
              {canEdit && (
                <button className="icon-btn" onClick={() => forget(e.id)} aria-label="Forget this example" title="Forget">
                  <Trash2 size={14} />
                </button>
              )}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
