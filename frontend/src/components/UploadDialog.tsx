import { useEffect, useRef, useState } from "react";
import { FileUp, Loader2, Plug, X } from "lucide-react";
import { api, errorMessage } from "../api";
import type { DatabaseInfo } from "../types";

interface Props {
  open: boolean;
  uploadedDatabases: DatabaseInfo[];
  canConnect: boolean;
  onClose: () => void;
  onUploaded: (db: DatabaseInfo) => void;
}

const ACCEPT = ".csv,.tsv,.txt,.db,.sqlite,.sqlite3";

export function UploadDialog({ open, canConnect, uploadedDatabases, onClose, onUploaded }: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [tab, setTab] = useState<"file" | "connect">("file");
  const [connName, setConnName] = useState("");
  const [connUrl, setConnUrl] = useState("");

  useEffect(() => {
    const d = dialogRef.current;
    if (!d) return;
    if (open && !d.open) {
      setFile(null);
      setTarget("");
      setError(null);
      setConnName("");
      setConnUrl("");
      d.showModal();
    } else if (!open && d.open) {
      d.close();
    }
  }, [open]);

  const isCsv = !!file && /\.(csv|tsv|txt)$/i.test(file.name);

  const submit = async () => {
    if (tab === "file" && !file) return;
    setBusy(true);
    setError(null);
    try {
      const db =
        tab === "connect"
          ? await api.connect(connName.trim(), connUrl.trim())
          : await api.upload(file!, isCsv && target ? target : undefined);
      onUploaded(db);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <dialog ref={dialogRef} className="dialog" onClose={onClose} onCancel={onClose}>
      <div className="dialog-header">
        <h2>Add your data</h2>
        <button className="icon-btn" onClick={onClose} aria-label="Close">
          <X size={16} />
        </button>
      </div>
      {canConnect && (<div className="segmented" role="tablist" aria-label="Source">
        <button role="tab" aria-selected={tab === "file"} className={tab === "file" ? "active" : ""} onClick={() => setTab("file")}>
          <FileUp size={14} /> Upload a file
        </button>
        <button
          role="tab"
          aria-selected={tab === "connect"}
          className={tab === "connect" ? "active" : ""}
          onClick={() => setTab("connect")}
        >
          <Plug size={14} /> Connect a database
        </button>
      </div>)}

      {tab === "connect" && (
        <div className="connect-form">
          <p className="muted">
            Connect a live PostgreSQL or MySQL database. Queries run read-only, and the connection string is stored encrypted
            on this server. Use a database user that can only read.
          </p>
          <label className="field">
            <span>Name</span>
            <input value={connName} onChange={(e) => setConnName(e.target.value)} placeholder="Sales warehouse" maxLength={60} />
          </label>
          <label className="field">
            <span>Connection URL</span>
            <input
              value={connUrl}
              onChange={(e) => setConnUrl(e.target.value)}
              placeholder="postgresql://user:password@host:5432/dbname"
              spellCheck={false}
              autoComplete="off"
              className="mono"
            />
          </label>
        </div>
      )}

      {tab === "file" && (<>
      <p className="muted">
        Upload a <strong>CSV</strong> file (becomes a table) or a <strong>SQLite</strong> database (.db, .sqlite). Files stay on
        this server.
      </p>

      <div
        className={"dropzone" + (dragging ? " dragging" : "") + (file ? " has-file" : "")}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const f = e.dataTransfer.files?.[0];
          if (f) setFile(f);
        }}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
      >
        <FileUp size={28} />
        {file ? (
          <span>
            <strong>{file.name}</strong> · {(file.size / 1024).toFixed(file.size > 102400 ? 0 : 1)} KB
          </span>
        ) : (
          <span>Drop a file here or click to choose</span>
        )}
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          hidden
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            e.target.value = "";
          }}
        />
      </div>

      {isCsv && uploadedDatabases.length > 0 && (
        <label className="field">
          <span>Add to</span>
          <select value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="">A new database</option>
            {uploadedDatabases.map((d) => (
              <option key={d.id} value={d.id}>
                Existing database: {d.name} (as a new table)
              </option>
            ))}
          </select>
        </label>
      )}
      </>)}

      {error && <p className="error-text">{error}</p>}

      <div className="dialog-actions">
        <button className="ghost-btn" onClick={onClose} disabled={busy}>
          Cancel
        </button>
        <button
          className="primary-btn"
          onClick={submit}
          disabled={busy || (tab === "file" ? !file : !connName.trim() || !connUrl.trim())}
        >
          {busy ? <Loader2 size={14} className="spin" /> : tab === "file" ? <FileUp size={14} /> : <Plug size={14} />}{" "}
          {tab === "file" ? "Upload" : "Connect"}
        </button>
      </div>
    </dialog>
  );
}
