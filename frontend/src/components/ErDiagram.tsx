import { useMemo, useState } from "react";
import { KeyRound, Link2 } from "lucide-react";
import type { Schema, Table } from "../types";

const W = 214;
const ROW = 22;
const HEAD = 34;
const GAP_X = 96;
const GAP_Y = 36;
const MAX_COLS = 10;

interface Node {
  table: Table;
  shown: Table["columns"];
  hidden: number;
  x: number;
  y: number;
  h: number;
}

interface Edge {
  from: string;
  to: string;
  path: string;
  label: string;
}

/** Order tables so that related ones sit next to each other (breadth-first from the most connected table). */
function orderTables(tables: Table[]): Table[] {
  const names = new Set(tables.map((t) => t.name));
  const links = new Map<string, Set<string>>(tables.map((t) => [t.name, new Set()]));
  for (const t of tables)
    for (const c of t.columns) {
      const ref = c.foreign_key?.split(".")[0];
      if (ref && ref !== t.name && names.has(ref)) {
        links.get(t.name)!.add(ref);
        links.get(ref)!.add(t.name);
      }
    }
  const byDegree = [...tables].sort((a, b) => links.get(b.name)!.size - links.get(a.name)!.size);
  const seen = new Set<string>();
  const out: Table[] = [];
  for (const start of byDegree) {
    if (seen.has(start.name)) continue;
    const queue = [start.name];
    seen.add(start.name);
    while (queue.length) {
      const name = queue.shift()!;
      out.push(tables.find((t) => t.name === name)!);
      for (const n of [...links.get(name)!].sort((a, b) => links.get(b)!.size - links.get(a)!.size))
        if (!seen.has(n)) {
          seen.add(n);
          queue.push(n);
        }
    }
  }
  return out;
}

function layout(schema: Schema) {
  const ordered = orderTables(schema.tables);
  const perRow = Math.max(1, Math.round(Math.sqrt(ordered.length * 1.1)));
  const nodes = new Map<string, Node>();
  let y = 0;
  for (let start = 0; start < ordered.length; start += perRow) {
    const row = ordered.slice(start, start + perRow);
    const prepared = row.map((table) => {
      const ranked = [...table.columns].sort(
        (a, b) => Number(b.primary_key) - Number(a.primary_key) || Number(!!b.foreign_key) - Number(!!a.foreign_key),
      );
      const shown = ranked.slice(0, MAX_COLS);
      const hidden = table.columns.length - shown.length;
      return { table, shown, hidden, h: HEAD + shown.length * ROW + (hidden > 0 ? ROW : 0) + 8 };
    });
    prepared.forEach((p, i) => nodes.set(p.table.name, { ...p, x: i * (W + GAP_X), y }));
    y += Math.max(...prepared.map((p) => p.h)) + GAP_Y;
  }

  const edges: Edge[] = [];
  for (const node of nodes.values())
    node.shown.forEach((c, i) => {
      const [refTable, refCol] = (c.foreign_key ?? "").split(".");
      const target = nodes.get(refTable);
      if (!target || target === node) return;
      const y1 = node.y + HEAD + i * ROW + ROW / 2;
      const ti = target.shown.findIndex((tc) => tc.name === refCol);
      const y2 = target.y + HEAD + (ti >= 0 ? ti : 0) * ROW + ROW / 2;
      let path: string;
      if (target.x === node.x) {
        const x = node.x + W;
        path = `M ${x} ${y1} C ${x + 70} ${y1}, ${x + 70} ${y2}, ${x} ${y2}`;
      } else {
        const right = target.x > node.x;
        const x1 = right ? node.x + W : node.x;
        const x2 = right ? target.x : target.x + W;
        const d = Math.max(40, Math.abs(x2 - x1) / 2);
        path = `M ${x1} ${y1} C ${x1 + (right ? d : -d)} ${y1}, ${x2 + (right ? -d : d)} ${y2}, ${x2} ${y2}`;
      }
      edges.push({ from: node.table.name, to: target.table.name, path, label: `${node.table.name}.${c.name} → ${c.foreign_key}` });
    });

  const list = [...nodes.values()];
  return {
    nodes: list,
    edges,
    width: Math.max(...list.map((n) => n.x + W)) + 2,
    height: Math.max(...list.map((n) => n.y + n.h)) + 2,
  };
}

/** Entity-relationship diagram drawn from the database's foreign keys. */
export function ErDiagram({ schema }: { schema: Schema }) {
  const [focus, setFocus] = useState<string | null>(null);
  const g = useMemo(() => layout(schema), [schema]);
  const related = (name: string) => g.edges.some((e) => (e.from === name || e.to === name) && (e.from === focus || e.to === focus));

  if (schema.tables.length === 0) return <p className="muted">This database has no tables.</p>;

  return (
    <div className="er">
      <div className="er-legend">
        <span>
          <KeyRound size={13} className="pk" /> primary key
        </span>
        <span>
          <Link2 size={13} className="fk" /> foreign key
        </span>
        <span className="muted">Hover a table to follow its relationships.</span>
      </div>
      {g.edges.length === 0 && <p className="muted">No foreign keys are defined, so there are no relationships to draw.</p>}
      <div className="er-scroll">
        <svg width={g.width} height={g.height} viewBox={`0 0 ${g.width} ${g.height}`} role="img" aria-label="Table relationships">
          {g.edges.map((e, i) => {
            const active = focus && (e.from === focus || e.to === focus);
            return (
              <g key={i} className={"er-edge" + (active ? " active" : focus ? " dim" : "")}>
                <title>{e.label}</title>
                <path d={e.path} />
              </g>
            );
          })}
          {g.nodes.map((n) => (
            <g
              key={n.table.name}
              transform={`translate(${n.x} ${n.y})`}
              className={"er-node" + (focus ? (n.table.name === focus || related(n.table.name) ? " on" : " dim") : "")}
              onMouseEnter={() => setFocus(n.table.name)}
              onMouseLeave={() => setFocus(null)}
            >
              <rect className="er-box" width={W} height={n.h} rx={8} />
              <path className="er-head" d={`M0 8a8 8 0 0 1 8-8h${W - 16}a8 8 0 0 1 8 8v${HEAD - 8}H0z`} />
              <text className="er-title" x={12} y={21}>
                {n.table.name}
              </text>
              <text className="er-count" x={W - 12} y={21} textAnchor="end">
                {n.table.row_count !== null ? n.table.row_count.toLocaleString() : ""}
              </text>
              {n.shown.map((c, i) => (
                <g key={c.name} transform={`translate(0 ${HEAD + i * ROW})`}>
                  <circle cx={14} cy={ROW / 2} r={3.5} className={c.primary_key ? "er-dot pk" : c.foreign_key ? "er-dot fk" : "er-dot"} />
                  <text className="er-col" x={26} y={ROW / 2 + 4}>
                    {c.name}
                  </text>
                  <text className="er-type" x={W - 12} y={ROW / 2 + 4} textAnchor="end">
                    {c.type.toLowerCase().replace(/\(.*\)/, "")}
                  </text>
                </g>
              ))}
              {n.hidden > 0 && (
                <text className="er-type" x={12} y={HEAD + n.shown.length * ROW + 15}>
                  + {n.hidden} more columns
                </text>
              )}
            </g>
          ))}
        </svg>
      </div>
    </div>
  );
}
