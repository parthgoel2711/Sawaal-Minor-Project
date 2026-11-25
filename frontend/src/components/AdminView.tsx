import { useCallback, useEffect, useState } from "react";
import { Loader2, Plus, RefreshCw, Trash2 } from "lucide-react";
import { api, errorMessage } from "../api";
import type { AuditRow, Role, UserRow } from "../types";

const ACTIONS = [
  "login", "ask", "run_sql", "teach_example", "teach_note", "forget", "add_document", "ask_documents",
  "upload_data", "connect_database", "delete_database", "suggest_charts", "denied", "create_user", "delete_user",
];

interface Props {
  authEnabled: boolean;
  onNotify: (message: string, kind?: "error") => void;
}

export function AdminView({ authEnabled, onNotify }: Props) {
  const [tab, setTab] = useState<"audit" | "users">("audit");
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Admin</h1>
          <p className="muted">Who asked what, and who can do what.</p>
        </div>
        <div className="segmented" role="tablist" aria-label="Admin sections">
          <button role="tab" aria-selected={tab === "audit"} className={tab === "audit" ? "active" : ""} onClick={() => setTab("audit")}>
            Audit log
          </button>
          <button role="tab" aria-selected={tab === "users"} className={tab === "users" ? "active" : ""} onClick={() => setTab("users")}>
            Users
          </button>
        </div>
      </header>
      {tab === "audit" ? <Audit onNotify={onNotify} /> : <Users authEnabled={authEnabled} onNotify={onNotify} />}
    </div>
  );
}

function Audit({ onNotify }: { onNotify: Props["onNotify"] }) {
  const [rows, setRows] = useState<AuditRow[] | null>(null);
  const [action, setAction] = useState("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await api.audit(action || undefined));
    } catch (e) {
      onNotify(errorMessage(e), "error");
    } finally {
      setLoading(false);
    }
  }, [action, onNotify]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <>
      <div className="audit-tools">
        <label className="field inline">
          <span>Show</span>
          <select value={action} onChange={(e) => setAction(e.target.value)}>
            <option value="">Everything</option>
            {ACTIONS.map((a) => (
              <option key={a} value={a}>
                {a.replace(/_/g, " ")}
              </option>
            ))}
          </select>
        </label>
        <button className="ghost-btn" onClick={load} disabled={loading}>
          {loading ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />} Refresh
        </button>
      </div>
      <div className="table-scroll audit-table">
        <table className="results">
          <thead>
            <tr>
              <th>Time</th>
              <th>User</th>
              <th>Action</th>
              <th>Database</th>
              <th>Detail</th>
              <th>Result</th>
            </tr>
          </thead>
          <tbody>
            {rows?.map((r) => (
              <tr key={r.id}>
                <td>{new Date(r.ts).toLocaleString([], { dateStyle: "short", timeStyle: "medium" })}</td>
                <td>
                  {r.username} <span className="muted">({r.role})</span>
                </td>
                <td>{r.action.replace(/_/g, " ")}</td>
                <td>{r.database_id ?? ""}</td>
                <td title={r.detail ?? ""}>{r.detail}</td>
                <td className={"audit-" + r.status}>{r.status}</td>
              </tr>
            ))}
            {rows && rows.length === 0 && (
              <tr>
                <td colSpan={6} className="empty-row">
                  Nothing recorded yet
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Users({ authEnabled, onNotify }: { authEnabled: boolean; onNotify: Props["onNotify"] }) {
  const [users, setUsers] = useState<UserRow[] | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("viewer");

  const load = useCallback(async () => {
    try {
      setUsers(await api.users());
    } catch (e) {
      onNotify(errorMessage(e), "error");
    }
  }, [onNotify]);

  useEffect(() => {
    load();
  }, [load]);

  const add = async () => {
    try {
      await api.addUser(username.trim(), password, role);
      setUsername("");
      setPassword("");
      load();
    } catch (e) {
      onNotify(errorMessage(e), "error");
    }
  };

  const remove = async (u: UserRow) => {
    if (!confirm(`Delete the user “${u.username}”?`)) return;
    try {
      await api.deleteUser(u.id);
      load();
    } catch (e) {
      onNotify(errorMessage(e), "error");
    }
  };

  return (
    <>
      {!authEnabled && (
        <div className="notice info">
          <div>
            Sign-in is off, so everyone is a local admin. Set <code>AUTH_ENABLED=true</code> in <code>.env</code> and restart to
            turn roles on.
          </div>
        </div>
      )}
      <div className="user-form">
        <label className="field">
          <span>Username</span>
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="off" />
        </label>
        <label className="field">
          <span>Password</span>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
        </label>
        <label className="field">
          <span>Role</span>
          <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            <option value="viewer">Viewer: ask and read</option>
            <option value="analyst">Analyst: also teach and upload</option>
            <option value="admin">Admin: everything</option>
          </select>
        </label>
        <button className="primary-btn" onClick={add} disabled={!username.trim() || password.length < 8}>
          <Plus size={14} /> Add user
        </button>
      </div>
      <ul className="user-list">
        {users?.map((u) => (
          <li key={u.id}>
            <span>{u.username}</span>
            <span className="muted">{u.role}</span>
            <button className="icon-btn" onClick={() => remove(u)} aria-label={`Delete ${u.username}`} title="Delete">
              <Trash2 size={14} />
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}
