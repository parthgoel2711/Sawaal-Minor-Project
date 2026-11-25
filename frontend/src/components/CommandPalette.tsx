import { useEffect, useMemo, useRef, useState } from "react";
import { CornerDownLeft, Search } from "lucide-react";

export interface Command {
  id: string;
  label: string;
  group: string;
  hint?: string;
  run: () => void;
}

interface Props {
  open: boolean;
  commands: Command[];
  onClose: () => void;
}

/** Ctrl/Cmd+K launcher: jump between pages, switch databases, run an example question. */
export function CommandPalette({ open, commands, onClose }: Props) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  const shown = useMemo(() => {
    const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    return commands.filter((c) => words.every((w) => `${c.label} ${c.group} ${c.hint ?? ""}`.toLowerCase().includes(w)));
  }, [commands, query]);

  useEffect(() => setActive(0), [query]);
  useEffect(() => {
    listRef.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  if (!open) return null;

  const choose = (c: Command | undefined) => {
    if (!c) return;
    onClose();
    c.run();
  };

  return (
    <div className="palette-overlay" onMouseDown={onClose}>
      <div className="palette" role="dialog" aria-label="Command palette" onMouseDown={(e) => e.stopPropagation()}>
        <label className="palette-input">
          <Search size={17} />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search pages, databases and example questions"
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setActive((a) => Math.min(a + 1, shown.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setActive((a) => Math.max(a - 1, 0));
              } else if (e.key === "Enter") {
                e.preventDefault();
                choose(shown[active]);
              } else if (e.key === "Escape") {
                onClose();
              }
            }}
          />
          <kbd>Esc</kbd>
        </label>
        <ul className="palette-list" ref={listRef} role="listbox">
          {shown.length === 0 && <li className="palette-empty">Nothing matches “{query}”.</li>}
          {shown.map((c, i) => (
            <li
              key={c.id}
              data-index={i}
              role="option"
              aria-selected={i === active}
              className={i === active ? "active" : ""}
              onMouseMove={() => setActive(i)}
              onClick={() => choose(c)}
            >
              <span className="palette-group">{c.group}</span>
              <span className="palette-label">{c.label}</span>
              {c.hint && <span className="muted palette-hint">{c.hint}</span>}
              {i === active && <CornerDownLeft size={14} className="muted" />}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
