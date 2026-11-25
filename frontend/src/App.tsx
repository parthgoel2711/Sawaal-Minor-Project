import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  BookOpen,
  GraduationCap,
  LogOut,
  ShieldCheck,
  Database,
  Home as HomeIcon,
  FileText,
  History as HistoryIcon,
  LayoutDashboard,
  MessageSquare,
  MessageSquarePlus,
  Moon,
  Network,
  PanelLeft,
  RefreshCw,
  Search,
  Sun,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { api, errorMessage } from "./api";
import { CommandPalette, type Command } from "./components/CommandPalette";
import { Composer } from "./components/Composer";
import { Dashboard } from "./components/Dashboard";
import { ExploreView } from "./components/ExploreView";
import { DocumentsView } from "./components/DocumentsView";
import { AdminView } from "./components/AdminView";
import { Home } from "./components/Home";
import { Login } from "./components/Login";
import { TrainingView } from "./components/TrainingView";
import { HistoryPanel } from "./components/HistoryPanel";
import { SchemaPanel } from "./components/SchemaPanel";
import { TurnCard } from "./components/TurnCard";
import { UploadDialog } from "./components/UploadDialog";
import { UsageView } from "./components/UsageView";
import { downloadText, newId } from "./lib/format";
import { buildReport } from "./lib/report";
import { load, save } from "./lib/storage";
import type { DatabaseInfo, Health, Me, HistoryItem, HistoryTurn, Schema, Theme, Turn, View } from "./types";

const MAX_CONTEXT_TURNS = 4;

function initialTheme(): Theme {
  const saved = load("theme");
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export default function App() {
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const [health, setHealth] = useState<Health | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [connectError, setConnectError] = useState<string | null>(null);
  const [databases, setDatabases] = useState<DatabaseInfo[]>([]);
  const [dbId, setDbId] = useState<string | null>(() => load("database"));
  const [schema, setSchema] = useState<Schema | null>(null);
  const [schemaLoading, setSchemaLoading] = useState(false);
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const [examples, setExamples] = useState<string[]>([]);
  const [turnsByDb, setTurnsByDb] = useState<Record<string, Turn[]>>({});
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [tab, setTab] = useState<"schema" | "history">("schema");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [mode, setMode] = useState<"ai" | "sql">("ai");
  const [view, setView] = useState<View>("home");
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [sqlDraft, setSqlDraft] = useState("");
  const [composerKey, setComposerKey] = useState(0);
  const [toast, setToast] = useState<{ text: string; kind: "ok" | "error" } | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const db = databases.find((d) => d.id === dbId) ?? null;
  const turns = useMemo(() => (dbId ? turnsByDb[dbId] ?? [] : []), [turnsByDb, dbId]);
  const busy = turns.some((t) => t.status === "thinking");
  const llmEnabled = !!health?.llm_enabled;
  const role = me?.user?.role ?? "viewer";
  const canTeach = role !== "viewer";
  const isAdmin = role === "admin";
  const showAdmin = isAdmin && !!me?.auth_enabled; // the Admin page (users, audit log) only matters when sign-in is on
  const needsLogin = !!me && me.auth_enabled && !me.user;
  const aiName = health?.provider === "groq" ? "Groq" : health?.provider === "anthropic" ? "Claude" : health?.provider === "demo" ? "Demo AI" : "AI";

  // ---------- theme ----------
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    save("theme", theme);
  }, [theme]);

  // ---------- Ctrl/Cmd+K ----------
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // ---------- toast ----------
  const notify = useCallback((text: string, kind: "ok" | "error" = "ok") => {
    setToast({ text, kind });
    window.setTimeout(() => setToast((t) => (t?.text === text ? null : t)), 4000);
  }, []);

  // ---------- initial load ----------
  const loadDatabases = useCallback(async () => {
    try {
      const [h, who] = await Promise.all([api.health(), api.me()]);
      setHealth(h);
      setMe(who);
      if (who.auth_enabled && !who.user) return [];
      const dbs = await api.databases();
      setDatabases(dbs);
      setConnectError(null);
      if (!h.llm_enabled) setMode("sql");
      return dbs;
    } catch (e) {
      setConnectError(errorMessage(e));
      return [];
    }
  }, []);

  useEffect(() => {
    loadDatabases();
  }, [loadDatabases]);

  // A request came back 401: the session ended, so go back to the sign-in page.
  useEffect(() => {
    const onUnauthorized = () => setMe((m) => (m ? { ...m, user: null } : m));
    window.addEventListener("sawaal:unauthorized", onUnauthorized);
    return () => window.removeEventListener("sawaal:unauthorized", onUnauthorized);
  }, []);

  const signOut = async () => {
    try {
      await api.logout();
    } finally {
      setDatabases([]);
      setTurnsByDb({});
      setView("home");
      setMe((m) => (m ? { ...m, user: null } : m));
    }
  };

  // Pick a valid database once the list is known.
  useEffect(() => {
    if (databases.length && !databases.some((d) => d.id === dbId)) setDbId(databases[0].id);
  }, [databases, dbId]);

  useEffect(() => {
    if (dbId) save("database", dbId);
  }, [dbId]);

  const refreshHistory = useCallback(async () => {
    if (!dbId) return;
    try {
      setHistory(await api.history(dbId));
    } catch {
      /* history is non-essential */
    }
  }, [dbId]);

  // Load schema, examples and history whenever the database changes.
  useEffect(() => {
    if (!dbId || !databases.some((d) => d.id === dbId)) return;
    let cancelled = false;
    setSchema(null);
    setSchemaError(null);
    setSchemaLoading(true);
    setExamples([]);
    api
      .schema(dbId)
      .then((s) => !cancelled && setSchema(s))
      .catch((e) => !cancelled && setSchemaError(errorMessage(e)))
      .finally(() => !cancelled && setSchemaLoading(false));
    api
      .examples(dbId)
      .then((ex) => !cancelled && setExamples(ex))
      .catch(() => {});
    refreshHistory();
    return () => {
      cancelled = true;
    };
  }, [dbId, databases, refreshHistory]);

  // Scroll to the newest turn when it's added and again when its answer arrives.
  const lastStatus = turns.at(-1)?.status;
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length, lastStatus]);

  // ---------- turns ----------
  const addTurn = (turn: Turn) =>
    setTurnsByDb((all) => ({ ...all, [turn.databaseId]: [...(all[turn.databaseId] ?? []), turn] }));

  const patchTurn = (databaseId: string, id: string, patch: Partial<Turn>) =>
    setTurnsByDb((all) => ({
      ...all,
      [databaseId]: (all[databaseId] ?? []).map((t) => (t.id === id ? { ...t, ...patch } : t)),
    }));

  const ask = async (text: string) => {
    if (!dbId || !text.trim()) return;
    const context: HistoryTurn[] = turns
      .filter((t) => t.status === "done" && t.sql && !t.error && !t.routedFrom)
      .slice(-MAX_CONTEXT_TURNS)
      .map((t) => ({ question: t.question ?? "(query written by the user)", sql: t.sql }));
    const turn: Turn = { id: newId(), databaseId: dbId, mode: "ai", question: text.trim(), sql: "", status: "thinking" };
    addTurn(turn);
    setQuestion("");
    try {
      const r = await api.generateStream({ database_id: dbId, question: turn.question!, history: context }, (message) =>
        setTurnsByDb((all) => ({
          ...all,
          [dbId]: (all[dbId] ?? []).map((t) =>
            t.id === turn.id && t.steps?.at(-1) !== message ? { ...t, steps: [...(t.steps ?? []), message] } : t,
          ),
        })),
      );
      patchTurn(dbId, turn.id, {
        usedMemory: r.used_memory,
        status: "done",
        sql: r.sql,
        explanation: r.explanation,
        answerable: r.answerable,
        result: r.result,
        error: r.error,
        attempts: r.attempts,
        historyId: r.history_id,
        queryDb: r.database_id,
        routedFrom: r.routed_from,
        summary: r.summary,
        followups: r.followups,
      });
    } catch (e) {
      patchTurn(dbId, turn.id, { status: "done", error: errorMessage(e) });
    }
    refreshHistory();
  };

  // Move an answer that came from another database into that database's conversation and switch to it.
  const switchToAnswerDb = (turn: Turn) => {
    const target = turn.queryDb;
    if (!target || target === turn.databaseId) return;
    setTurnsByDb((all) => ({
      ...all,
      [turn.databaseId]: (all[turn.databaseId] ?? []).filter((t) => t.id !== turn.id),
      [target]: [...(all[target] ?? []), { ...turn, databaseId: target, routedFrom: null }],
    }));
    setDbId(target);
  };

  const teach = async (turn: Turn, sql: string) => {
    if (!turn.question) return;
    try {
      await api.teachExample(turn.queryDb ?? turn.databaseId, turn.question, sql);
      notify("Saved. Similar questions will now see this SQL");
    } catch (e) {
      notify(errorMessage(e), "error");
      throw e;
    }
  };

  const dbName = (id: string) => databases.find((d) => d.id === id)?.name ?? id;

  const runSql = async (sql: string, label?: string) => {
    if (!dbId || !sql.trim()) return;
    const turn: Turn = { id: newId(), databaseId: dbId, mode: "sql", question: label, sql: sql.trim(), status: "running" };
    addTurn(turn);
    try {
      const r = await api.execute({ database_id: dbId, sql, question: label });
      patchTurn(dbId, turn.id, { status: "done", sql: r.sql, result: r.result, error: r.error, historyId: r.history_id });
    } catch (e) {
      patchTurn(dbId, turn.id, { status: "done", error: errorMessage(e) });
    }
    refreshHistory();
  };

  const rerun = async (turn: Turn, sql: string) => {
    patchTurn(turn.databaseId, turn.id, { status: "running" });
    try {
      const r = await api.execute({ database_id: turn.queryDb ?? turn.databaseId, sql, question: turn.question });
      patchTurn(turn.databaseId, turn.id, {
        status: "done",
        sql: r.sql,
        result: r.result ?? turn.result,
        error: r.error,
        answerable: true,
        attempts: [],
        historyId: r.history_id ?? turn.historyId,
      });
    } catch (e) {
      patchTurn(turn.databaseId, turn.id, { status: "done", error: errorMessage(e) });
    }
    refreshHistory();
  };

  const submit = () => {
    if (mode === "ai") ask(question);
    else {
      runSql(sqlDraft);
      setSqlDraft("");
      setComposerKey((k) => k + 1);
    }
  };

  const pinned = useMemo(() => new Set(history.filter((h) => h.starred).map((h) => h.id)), [history]);

  const togglePin = async (turn: Turn) => {
    if (turn.historyId == null) return;
    const pin = !pinned.has(turn.historyId);
    try {
      const updated = await api.starHistory(turn.historyId, pin);
      setHistory((h) => h.map((i) => (i.id === updated.id ? updated : i)));
      notify(pin ? "Pinned to your dashboard." : "Removed from your dashboard.");
    } catch (e) {
      notify(errorMessage(e), "error");
    }
  };

  const newConversation = () => dbId && setTurnsByDb((all) => ({ ...all, [dbId]: [] }));

  // ---------- history actions ----------
  const openHistory = (item: HistoryItem) => {
    setSidebarOpen(false);
    runSql(item.sql, item.question ?? undefined);
  };
  const starHistory = async (item: HistoryItem) => {
    try {
      const updated = await api.starHistory(item.id, !item.starred);
      setHistory((h) => h.map((i) => (i.id === item.id ? updated : i)));
    } catch (e) {
      notify(errorMessage(e), "error");
    }
  };
  const deleteHistory = async (item: HistoryItem) => {
    try {
      await api.deleteHistory(item.id);
      setHistory((h) => h.filter((i) => i.id !== item.id));
    } catch (e) {
      notify(errorMessage(e), "error");
    }
  };
  const clearHistory = async () => {
    if (!dbId) return;
    try {
      await api.clearHistory(dbId);
      refreshHistory();
    } catch (e) {
      notify(errorMessage(e), "error");
    }
  };

  // ---------- databases ----------
  const onUploaded = async (info: DatabaseInfo) => {
    setUploadOpen(false);
    await loadDatabases();
    setDbId(info.id);
    // re-read the schema even if the same database was selected (a table may have been added)
    if (info.id === dbId) {
      setSchemaLoading(true);
      api.schema(info.id).then(setSchema).finally(() => setSchemaLoading(false));
    }
    notify(`“${info.name}” is ready`);
  };

  const deleteDatabase = async () => {
    if (!db?.deletable) return;
    if (!confirm(`Delete the database “${db.name}”? This can't be undone.`)) return;
    try {
      await api.deleteDatabase(db.id);
      setTurnsByDb(({ [db.id]: _removed, ...rest }) => rest);
      await loadDatabases();
      notify(`Deleted “${db.name}”.`);
    } catch (e) {
      notify(errorMessage(e), "error");
    }
  };

  const previewTable = (table: string) => {
    setSidebarOpen(false);
    const quoted = /^[a-z_][a-z0-9_]*$/i.test(table) ? table : `"${table.replace(/"/g, '""')}"`;
    runSql(`SELECT * FROM ${quoted} LIMIT 50`, `Preview of ${table}`);
  };

  const downloadReport = () => {
    const html = buildReport(turns, db?.name ?? "database");
    downloadText(`sawaal-report-${new Date().toISOString().slice(0, 10)}.html`, html, "text/html;charset=utf-8");
    notify("Report downloaded. Open it in a browser or print it to PDF.");
  };

  const commands: Command[] = [
    ...(
      [
        ["home", "Home"],
        ["ask", "Ask a question"],
        ["documents", "Documents"],
        ["training", "Training"],
        ["dashboard", "Dashboard"],
        ["explore", "Explore data"],
        ["usage", "Usage"],
        ...(showAdmin ? [["admin", "Admin"]] : []),
      ] as [View, string][]
    ).map(([v, label]) => ({ id: `view-${v}`, group: "Go to", label, run: () => setView(v) })),
    ...databases
      .filter((d) => d.id !== dbId)
      .map((d) => ({ id: `db-${d.id}`, group: "Switch database", label: d.name, run: () => setDbId(d.id) })),
    { id: "upload", group: "Action", label: "Add data", hint: "Upload a file or connect a database", run: () => setUploadOpen(true) },
    { id: "theme", group: "Action", label: theme === "dark" ? "Switch to light theme" : "Switch to dark theme", run: () => setTheme(theme === "dark" ? "light" : "dark") },
    { id: "new", group: "Action", label: "Start a new conversation", run: () => { setView("ask"); newConversation(); } },
    ...(turns.length ? [{ id: "report", group: "Action", label: "Download report of this conversation", run: downloadReport }] : []),
    ...(llmEnabled
      ? examples.map((q) => ({ id: `ex-${q}`, group: "Try asking", label: q, run: () => { setView("ask"); ask(q); } }))
      : []),
  ];

  // ---------- render ----------
  if (connectError && !health) {
    return (
      <div className="fatal">
        <Database size={32} />
        <h1>Can't connect to the server</h1>
        <p>{connectError}</p>
        <p className="muted">
          Start the backend with <code>python -m app</code> in the <code>backend</code> folder, then try again.
        </p>
        <button className="primary-btn" onClick={loadDatabases}>
          <RefreshCw size={14} /> Retry
        </button>
      </div>
    );
  }

  if (needsLogin) return <Login onDone={loadDatabases} />;

  const uploaded = databases.filter((d) => d.kind === "upload");
  const totalRows = schema?.tables.reduce((n, t) => n + (t.row_count ?? 0), 0) ?? 0;

  const nav: { id: View; label: string; icon: typeof MessageSquare; badge?: number }[] = [
    { id: "home", label: "Home", icon: HomeIcon },
    { id: "ask", label: "Ask", icon: MessageSquare },
    { id: "documents", label: "Documents", icon: BookOpen },
    { id: "training", label: "Training", icon: GraduationCap },
    { id: "dashboard", label: "Dashboard", icon: LayoutDashboard, badge: pinned.size || undefined },
    { id: "explore", label: "Explore", icon: Network },
    { id: "usage", label: "Usage", icon: Activity },
    ...(showAdmin ? [{ id: "admin" as View, label: "Admin", icon: ShieldCheck }] : []),
  ];

  return (
    <div className="shell">
      <nav className="rail" aria-label="Main">
        <button className="brand" title="Sawaal home" aria-label="Home" onClick={() => setView("home")}>
          <img src="/favicon.svg" alt="" width={28} height={28} />
        </button>
        {nav.map(({ id, label, icon: Icon, badge }) => (
          <button
            key={id}
            className={"rail-btn" + (view === id ? " active" : "")}
            aria-current={view === id ? "page" : undefined}
            onClick={() => {
              setView(id);
              setSidebarOpen(false);
            }}
          >
            <span className="rail-icon">
              <Icon size={19} />
              {badge !== undefined && <span className="rail-badge">{badge}</span>}
            </span>
            <span>{label}</span>
          </button>
        ))}
        <div className="rail-spacer" />
        <button
          className="rail-btn"
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
        >
          <span className="rail-icon">{theme === "dark" ? <Sun size={19} /> : <Moon size={19} />}</span>
          <span>{theme === "dark" ? "Light" : "Dark"}</span>
        </button>
        {me?.auth_enabled && me.user && (
          <button className="rail-btn" onClick={signOut} title={`Signed in as ${me.user.username} (${me.user.role}). Click to sign out`}>
            <span className="rail-icon">
              <LogOut size={19} />
            </span>
            <span className="rail-user">{me.user.username}</span>
          </button>
        )}
      </nav>

      <div className="stage">
        <header className="bar">
          {view === "ask" && (
            <button className="icon-btn panel-toggle" onClick={() => setSidebarOpen((o) => !o)} aria-label="Toggle schema and history">
              {sidebarOpen ? <X size={18} /> : <PanelLeft size={18} />}
            </button>
          )}
          <span className="wordmark" aria-label="Sawaal">
            Sawaal
          </span>
          <div className="db-picker">
            <Database size={16} />
            <select value={dbId ?? ""} onChange={(e) => setDbId(e.target.value)} aria-label="Database">
              {databases.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                  {d.kind === "upload" ? " (uploaded)" : d.kind === "external" ? ` (${d.dialect})` : ""}
                </option>
              ))}
            </select>
            {db?.deletable && isAdmin && (
              <button className="icon-btn" onClick={deleteDatabase} title="Delete this database" aria-label="Delete database">
                <Trash2 size={15} />
              </button>
            )}
          </div>
          <div className="bar-actions">
            <button className="search-btn" onClick={() => setPaletteOpen(true)} aria-label="Open command palette">
              <Search size={14} /> <span className="hide-sm">Search</span> <kbd className="hide-sm">⌘K</kbd>
            </button>
            {canTeach && (
              <button className="ghost-btn" onClick={() => setUploadOpen(true)}>
                <Upload size={15} /> <span className="hide-sm">Add data</span>
              </button>
            )}
            <span
              className={"status-pill " + (llmEnabled ? "on" : "off")}
              title={llmEnabled ? `Using ${health?.model}` : "Set ANTHROPIC_API_KEY or GROQ_API_KEY in .env to enable AI questions"}
            >
              <span className="dot" /> {llmEnabled ? `${aiName} ready` : "AI off"}
            </span>
          </div>
        </header>

        <div className={"workspace" + (view === "ask" ? " with-panel" : "")}>
          {view === "ask" && (
            <aside className={"sidebar" + (sidebarOpen ? " open" : "")}>
              <div className="sidebar-tabs" role="tablist">
                <button role="tab" aria-selected={tab === "schema"} className={tab === "schema" ? "active" : ""} onClick={() => setTab("schema")}>
                  <Database size={14} /> Tables
                </button>
                <button role="tab" aria-selected={tab === "history"} className={tab === "history" ? "active" : ""} onClick={() => setTab("history")}>
                  <HistoryIcon size={14} /> History {history.length > 0 && <span className="badge">{history.length}</span>}
                </button>
              </div>
              <div className="sidebar-body">
                {tab === "schema" ? (
                  <SchemaPanel schema={schema} loading={schemaLoading} error={schemaError} onPreview={previewTable} />
                ) : (
                  <HistoryPanel items={history} onOpen={openHistory} onStar={starHistory} onDelete={deleteHistory} onClear={clearHistory} />
                )}
              </div>
            </aside>
          )}
          {view === "ask" && sidebarOpen && <div className="scrim" onClick={() => setSidebarOpen(false)} />}

          <main className="main">
            {view === "home" && (
              <Home
                databases={databases}
                llmEnabled={llmEnabled}
                aiName={aiName}
                onOpenDb={(id) => {
                  setDbId(id);
                  setView("ask");
                }}
                onGo={setView}
                onUpload={() => setUploadOpen(true)}
              />
            )}
            {view === "training" && dbId && (
              <TrainingView key={dbId} databaseId={dbId} databaseName={db?.name ?? dbId} canEdit={canTeach} onNotify={notify} />
            )}
            {view === "admin" && showAdmin && <AdminView authEnabled={!!me?.auth_enabled} onNotify={notify} />}
            {view === "documents" && (
              <DocumentsView databases={databases} defaultDb={dbId} llmEnabled={llmEnabled} onNotify={notify} />
            )}
            {view === "dashboard" && dbId && (
              <Dashboard
                key={dbId}
                databaseId={dbId}
                databaseName={db?.name ?? dbId}
                theme={theme}
                onChanged={refreshHistory}
                onBack={() => setView("ask")}
              />
            )}
            {view === "explore" && dbId && <ExploreView key={dbId} databaseId={dbId} databaseName={db?.name ?? dbId} schema={schema} />}
            {view === "usage" && dbId && <UsageView key={dbId} databaseId={dbId} databaseName={db?.name ?? dbId} />}

            {view === "ask" && (
              <>
                <div className="conversation">
                  {turns.length === 0 ? (
                    <section className="welcome">
                      <h1>Ask your data a question</h1>
                      <p className="lede">
                        {db?.description ? db.description.replace(/([^.!?])$/, "$1.") : "Type a question in plain English."}
                      </p>
                      {schema && (
                        <p className="facts">
                          {schema.tables.length} tables, {totalRows.toLocaleString()} rows. {aiName} writes the SQL, runs it read-only
                          and shows you the answer.
                        </p>
                      )}
                      {!llmEnabled && health && (
                        <div className="notice info">
                          <div>
                            <strong>AI questions are turned off.</strong>
                            <p>
                              Add <code>GROQ_API_KEY=…</code> (free) or <code>ANTHROPIC_API_KEY=…</code> to the <code>.env</code> file and
                              restart the server. You can still browse the schema and run your own SQL.
                            </p>
                          </div>
                        </div>
                      )}
                      {examples.length > 0 && llmEnabled && (
                        <div className="examples">
                          <h2>Try asking</h2>
                          <ul className="prompts">
                            {examples.map((q) => (
                              <li key={q}>
                                <button className="prompt" onClick={() => ask(q)} disabled={busy}>
                                  {q}
                                </button>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </section>
                  ) : (
                    <>
                      <div className="conversation-head">
                        <button className="ghost-btn" onClick={downloadReport} disabled={busy} title="Download this conversation as a report">
                          <FileText size={15} /> Report
                        </button>
                        <button className="ghost-btn" onClick={newConversation} disabled={busy}>
                          <MessageSquarePlus size={15} /> New conversation
                        </button>
                      </div>
                      {turns.map((t) => (
                        <TurnCard
                          key={t.id}
                          turn={t}
                          schema={schema}
                          dialect={db?.dialect ?? "sqlite"}
                          theme={theme}
                          onRun={rerun}
                          dbName={dbName}
                          onSwitchDb={switchToAnswerDb}
                          onAsk={ask}
                          pinned={t.historyId != null && pinned.has(t.historyId)}
                          onPin={togglePin}
                          onTeach={canTeach ? teach : undefined}
                          canAsk={llmEnabled && !busy}
                          llmEnabled={llmEnabled}
                        />
                      ))}
                    </>
                  )}
                  <div ref={endRef} />
                </div>

                <Composer
                  mode={mode}
                  onModeChange={setMode}
                  question={question}
                  onQuestionChange={setQuestion}
                  sql={sqlDraft}
                  onSqlChange={setSqlDraft}
                  onSubmit={submit}
                  busy={busy}
                  llmEnabled={llmEnabled}
                  followUp={turns.some((t) => t.status === "done" && !!t.sql)}
                  schema={schema}
                  dialect={db?.dialect ?? "sqlite"}
                  theme={theme}
                  resetKey={composerKey}
                />
              </>
            )}
          </main>
        </div>
      </div>

      <CommandPalette open={paletteOpen} commands={commands} onClose={() => setPaletteOpen(false)} />
      <UploadDialog canConnect={isAdmin} open={uploadOpen} uploadedDatabases={uploaded} onClose={() => setUploadOpen(false)} onUploaded={onUploaded} />

      {toast && (
        <div className={"toast " + toast.kind} role="status">
          {toast.text}
        </div>
      )}
    </div>
  );
}
