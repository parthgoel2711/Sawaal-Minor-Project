import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import { api, errorMessage } from "../api";
import type { Profile, ProfileColumn, ProfileTable, Schema } from "../types";
import { ErDiagram } from "./ErDiagram";

interface Props {
  databaseId: string;
  databaseName: string;
  schema: Schema | null;
}

export function ExploreView({ databaseId, databaseName, schema }: Props) {
  const [tab, setTab] = useState<"relationships" | "quality">("relationships");
  const [profile, setProfile] = useState<Profile | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setProfile(null);
    setError(null);
    api
      .profile(databaseId)
      .then((p) => !cancelled && setProfile(p))
      .catch((e) => !cancelled && setError(errorMessage(e)));
    return () => {
      cancelled = true;
    };
  }, [databaseId]);

  const totalRows = profile?.tables.reduce((n, t) => n + t.row_count, 0) ?? 0;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Explore {databaseName}</h1>
          <p className="muted">See how the tables connect and how clean the data is before you ask questions.</p>
        </div>
        <div className="segmented" role="tablist" aria-label="Explore">
          <button role="tab" aria-selected={tab === "relationships"} className={tab === "relationships" ? "active" : ""} onClick={() => setTab("relationships")}>
            Relationships
          </button>
          <button role="tab" aria-selected={tab === "quality"} className={tab === "quality" ? "active" : ""} onClick={() => setTab("quality")}>
            Data quality
            {profile && profile.issues > 0 && <span className="badge warn">{profile.issues}</span>}
          </button>
        </div>
      </header>

      {tab === "relationships" &&
        (schema ? <ErDiagram schema={schema} /> : <p className="muted"><Loader2 size={14} className="spin" /> Reading schema…</p>)}

      {tab === "quality" && (
        <>
          {error && <div className="notice error">{error}</div>}
          {!profile && !error && (
            <p className="muted">
              <Loader2 size={14} className="spin" /> Checking every column…
            </p>
          )}
          {profile && (
            <>
              <dl className="figures">
                <div>
                  <dt>Tables</dt>
                  <dd>{profile.tables.length}</dd>
                </div>
                <div>
                  <dt>Rows</dt>
                  <dd>{totalRows.toLocaleString()}</dd>
                </div>
                <div>
                  <dt>Cells filled in</dt>
                  <dd>{profile.completeness}%</dd>
                </div>
                <div>
                  <dt>Columns to check</dt>
                  <dd className={profile.issues ? "warn-text" : ""}>{profile.issues}</dd>
                </div>
              </dl>
              <div className="profile-list">
                {profile.tables.map((t, i) => (
                  <ProfileSection key={t.name} table={t} startOpen={i === 0} />
                ))}
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}

function shorten(v: unknown): string {
  if (v === null || v === undefined) return "–";
  const s = typeof v === "number" ? (Number.isInteger(v) ? v.toLocaleString() : String(Math.round(v * 100) / 100)) : String(v);
  return s.length > 22 ? s.slice(0, 21) + "…" : s;
}

function ProfileSection({ table, startOpen }: { table: ProfileTable; startOpen: boolean }) {
  const [open, setOpen] = useState(startOpen);
  const flagged = useMemo(
    () => table.columns.filter((c) => c.flags.some((f) => f === "mostly empty" || f === "constant")).length,
    [table],
  );
  return (
    <section className="profile-table">
      <button className="profile-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        <span className="profile-name">{table.name}</span>
        <span className="muted">{table.row_count.toLocaleString()} rows</span>
        {flagged > 0 && <span className="badge warn">{flagged} to check</span>}
        <span className="meter" title={`${table.completeness}% of cells are filled in`}>
          <span style={{ width: `${table.completeness}%` }} />
        </span>
        <span className="meter-label">{table.completeness}%</span>
      </button>
      {open && (
        <div className="table-scroll">
          <table className="results profile-cols">
            <thead>
              <tr>
                <th>Column</th>
                <th>Type</th>
                <th>Empty</th>
                <th className="num">Distinct</th>
                <th>Range</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {table.columns.map((c) => (
                <ProfileRow key={c.name} column={c} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function ProfileRow({ column: c }: { column: ProfileColumn }) {
  return (
    <tr>
      <td className="mono">{c.name}</td>
      <td className="muted mono">{c.type.toLowerCase()}</td>
      <td>
        <span className="empty-cell">
          <span className="meter small">
            <span className={c.null_pct >= 50 ? "bad" : ""} style={{ width: `${c.null_pct}%` }} />
          </span>
          {c.null_pct}%
        </span>
      </td>
      <td className="num">{c.distinct.toLocaleString()}</td>
      <td className="muted">{c.min === null && c.max === null ? "–" : `${shorten(c.min)} to ${shorten(c.max)}`}</td>
      <td>
        {c.flags.map((f) => (
          <span key={f} className={"tag" + (f === "unique" ? "" : " warn")}>
            {f}
          </span>
        ))}
      </td>
    </tr>
  );
}
