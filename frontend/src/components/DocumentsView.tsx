import { useCallback, useEffect, useRef, useState } from "react";
import { FileText, Loader2, SendHorizontal, Trash2, Upload } from "lucide-react";
import { api, errorMessage } from "../api";
import type { DatabaseInfo, DocAnswer, DocumentInfo } from "../types";

interface Props {
  databases: DatabaseInfo[];
  defaultDb: string | null;
  llmEnabled: boolean;
  onNotify: (message: string, kind?: "error") => void;
}

interface Exchange {
  question: string;
  answer?: DocAnswer;
  error?: string;
}

/** Answers cite passages as [1], [2]. Turn each into a marker that points at the numbered source below. */
function withCitations(text: string) {
  return text.split(/(\[\d+\])/g).map((part, i) =>
    /^\[\d+\]$/.test(part) ? (
      <sup key={i} className="cite">
        {part.slice(1, -1)}
      </sup>
    ) : (
      part
    ),
  );
}

export function DocumentsView({ databases, defaultDb, llmEnabled, onNotify }: Props) {
  const [docs, setDocs] = useState<DocumentInfo[] | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [question, setQuestion] = useState("");
  const [useDb, setUseDb] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [thread, setThread] = useState<Exchange[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      setDocs(await api.documents());
    } catch (e) {
      onNotify(errorMessage(e), "error");
      setDocs([]);
    }
  }, [onNotify]);

  useEffect(() => {
    load();
  }, [load]);

  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setUploading(true);
    for (const f of Array.from(files)) {
      try {
        await api.uploadDocument(f);
      } catch (e) {
        onNotify(`${f.name}: ${errorMessage(e)}`, "error");
      }
    }
    setUploading(false);
    load();
  };

  const remove = async (d: DocumentInfo) => {
    if (!confirm(`Delete “${d.name}”? This can't be undone.`)) return;
    try {
      await api.deleteDocument(d.id);
      setSelected((s) => {
        const n = new Set(s);
        n.delete(d.id);
        return n;
      });
      load();
    } catch (e) {
      onNotify(errorMessage(e), "error");
    }
  };

  const ask = async () => {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true);
    setQuestion("");
    const idx = thread.length;
    setThread((t) => [...t, { question: q }]);
    try {
      const answer = await api.askDocuments({
        question: q,
        document_ids: selected.size ? [...selected] : undefined,
        database_id: useDb || undefined,
      });
      setThread((t) => t.map((x, i) => (i === idx ? { ...x, answer } : x)));
    } catch (e) {
      setThread((t) => t.map((x, i) => (i === idx ? { ...x, error: errorMessage(e) } : x)));
    } finally {
      setBusy(false);
    }
  };

  const toggle = (id: number) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  const empty = docs !== null && docs.length === 0;

  return (
    <div className="page docs">
      <header className="page-head">
        <div>
          <h1>Documents</h1>
          <p className="muted">
            Upload PDFs or text files and ask questions about them. Answers cite the passages they came from, and can also
            use numbers from a database.
          </p>
        </div>
      </header>

      <div className="docs-layout">
        <aside className="docs-list">
          <button className="ghost-btn docs-upload" onClick={() => fileRef.current?.click()} disabled={uploading}>
            {uploading ? <Loader2 size={15} className="spin" /> : <Upload size={15} />} Add documents
          </button>
          <input
            ref={fileRef}
            type="file"
            hidden
            multiple
            accept=".pdf,.txt,.md,.markdown,.csv,.log"
            onChange={(e) => {
              upload(e.target.files);
              e.target.value = "";
            }}
          />
          {docs === null && <p className="muted small">Loading</p>}
          {empty && <p className="muted small">No documents yet. PDF, TXT, MD and CSV files work.</p>}
          <ul>
            {docs?.map((d) => (
              <li key={d.id} className={selected.has(d.id) ? "on" : ""}>
                <label>
                  <input type="checkbox" checked={selected.has(d.id)} onChange={() => toggle(d.id)} />
                  <FileText size={15} />
                  <span className="docs-name" title={d.name}>
                    {d.name}
                  </span>
                </label>
                <span className="docs-meta">
                  {d.pages} {d.pages === 1 ? "page" : "pages"} · {d.chunks} passages
                </span>
                <button className="icon-btn" onClick={() => remove(d)} aria-label={`Delete ${d.name}`} title="Delete">
                  <Trash2 size={14} />
                </button>
              </li>
            ))}
          </ul>
          {docs && docs.length > 0 && (
            <p className="muted small">{selected.size ? `Searching ${selected.size} selected.` : "Searching all documents."}</p>
          )}
        </aside>

        <section className="docs-chat">
          <div className="docs-thread">
            {thread.length === 0 && (
              <div className="empty-state">
                <h3>Ask about your documents</h3>
                <p className="muted">
                  For example: “What is the notice period?” or “What does the policy say about leave?”. Pick a database below
                  to combine document text with live numbers.
                </p>
              </div>
            )}
            {thread.map((x, i) => (
              <article key={i} className="turn">
                <h2 className="turn-question">{x.question}</h2>
                {!x.answer && !x.error && (
                  <div className="thinking" role="status">
                    <Loader2 size={16} className="spin" /> <span className="muted">Searching your documents</span>
                  </div>
                )}
                {x.error && (
                  <div className="notice error" role="alert">
                    <div>{x.error}</div>
                  </div>
                )}
                {x.answer && (
                  <>
                    {x.answer.answer ? (
                      <div className={"insight" + (x.answer.found ? "" : " unfound")}>
                        <p>{withCitations(x.answer.answer)}</p>
                      </div>
                    ) : (
                      <div className="notice info">
                        <div>
                          {x.answer.sources.length
                            ? "AI is off, so here are the passages that match best."
                            : "Nothing in your documents matches."}
                        </div>
                      </div>
                    )}
                    {x.answer.sources.length > 0 && (
                      <ol className="sources">
                        {x.answer.sources.map((s) => (
                          <li key={s.n}>
                            <span className="sources-n">{s.n}</span>
                            <div>
                              <div className="sources-head">
                                {s.document}
                                {s.kind === "document" && s.page ? `, page ${s.page}` : s.kind === "database" ? " (database)" : ""}
                              </div>
                              <p className={s.kind === "database" ? "mono" : ""}>{s.text}</p>
                            </div>
                          </li>
                        ))}
                      </ol>
                    )}
                    {x.answer.sql && (
                      <details className="sources-sql">
                        <summary>SQL used for the database part</summary>
                        <pre>{x.answer.sql}</pre>
                      </details>
                    )}
                  </>
                )}
              </article>
            ))}
          </div>

          <div className="docs-composer">
            <div className="docs-composer-top">
              <label className="field inline">
                <span>Also use data from</span>
                <select value={useDb} onChange={(e) => setUseDb(e.target.value)} disabled={!llmEnabled}>
                  <option value="">No database</option>
                  {databases.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
                    </option>
                  ))}
                </select>
              </label>
              {defaultDb && useDb === "" && databases.some((d) => d.id === defaultDb) && (
                <button className="link-btn" onClick={() => setUseDb(defaultDb)}>
                  Use {databases.find((d) => d.id === defaultDb)?.name}
                </button>
              )}
            </div>
            <div className="composer-box">
              <textarea
                rows={1}
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder={empty ? "Add a document first" : "Ask a question about your documents"}
                disabled={empty}
                aria-label="Question"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    ask();
                  }
                }}
              />
              <button className="send-btn" onClick={ask} disabled={busy || empty || !question.trim()} aria-label="Ask">
                {busy ? <Loader2 size={18} className="spin" /> : <SendHorizontal size={18} />}
              </button>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
