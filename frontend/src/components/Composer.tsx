import { useEffect, useRef, useState } from "react";
import { Code2, Loader2, Mic, MicOff, SendHorizontal, Sparkles } from "lucide-react";
import type { Schema, Theme } from "../types";
import { SqlEditor } from "./SqlEditor";

interface Props {
  mode: "ai" | "sql";
  onModeChange: (mode: "ai" | "sql") => void;
  question: string;
  onQuestionChange: (v: string) => void;
  sql: string;
  onSqlChange: (v: string) => void;
  onSubmit: () => void;
  busy: boolean;
  llmEnabled: boolean;
  followUp: boolean;
  schema: Schema | null;
  dialect: string;
  theme: Theme;
  /** Changing this remounts the SQL editor, which is how it gets cleared after a run. */
  resetKey: number;
}

/** Minimal typing for the browser's speech recognition (Chrome, Edge and Safari). */
interface Recognizer {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}
type RecognizerCtor = new () => Recognizer;

function speechCtor(): RecognizerCtor | null {
  const w = window as unknown as { SpeechRecognition?: RecognizerCtor; webkitSpeechRecognition?: RecognizerCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

const VOICE_LANGS = [
  { code: "en-IN", label: "EN" },
  { code: "hi-IN", label: "हिं" },
];

export function Composer(props: Props) {
  const { mode, onModeChange, question, onQuestionChange, sql, onSqlChange, onSubmit, busy, llmEnabled, followUp } = props;
  const textRef = useRef<HTMLTextAreaElement>(null);
  const recRef = useRef<Recognizer | null>(null);
  const baseRef = useRef("");
  const [listening, setListening] = useState(false);
  const [langIdx, setLangIdx] = useState(0);
  const voiceSupported = speechCtor() !== null;

  const stopVoice = () => {
    recRef.current?.stop();
    recRef.current = null;
    setListening(false);
  };

  const toggleVoice = () => {
    if (listening) return stopVoice();
    const Ctor = speechCtor();
    if (!Ctor) return;
    const rec = new Ctor();
    rec.lang = VOICE_LANGS[langIdx].code;
    rec.interimResults = true;
    rec.continuous = false;
    baseRef.current = question.trim() ? question.trim() + " " : "";
    rec.onresult = (e) => {
      const text = Array.from(e.results, (r) => r[0].transcript).join("");
      onQuestionChange(baseRef.current + text);
    };
    rec.onerror = () => stopVoice();
    rec.onend = () => {
      recRef.current = null;
      setListening(false);
    };
    recRef.current = rec;
    setListening(true);
    rec.start();
  };

  // Stop listening when the user leaves the question box or sends it.
  useEffect(() => {
    if (busy || mode !== "ai") stopVoice();
  }, [busy, mode]);
  useEffect(() => () => recRef.current?.stop(), []);

  // Grow the textarea with its content, and re-fit when the window (and so the line width) changes.
  useEffect(() => {
    const el = textRef.current;
    if (!el) return;
    const fit = () => {
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 200) + "px";
    };
    fit();
    let width = el.clientWidth;
    const observer = new ResizeObserver(() => {
      if (el.clientWidth !== width) {
        width = el.clientWidth;
        fit();
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [question, mode]);

  const canSubmit = !busy && (mode === "ai" ? question.trim().length > 0 && llmEnabled : sql.trim().length > 0);

  return (
    <div className="composer">
      <div className="composer-top">
        <div className="segmented" role="tablist" aria-label="Input mode">
          <button
            role="tab"
            aria-selected={mode === "ai"}
            className={mode === "ai" ? "active" : ""}
            onClick={() => onModeChange("ai")}
          >
            <Sparkles size={14} /> Ask in English
          </button>
          <button
            role="tab"
            aria-selected={mode === "sql"}
            className={mode === "sql" ? "active" : ""}
            onClick={() => onModeChange("sql")}
          >
            <Code2 size={14} /> Write SQL
          </button>
        </div>
        {mode === "ai" && followUp && <span className="hint">Follow-up questions use the conversation so far</span>}
      </div>

      <div className="composer-box">
        {mode === "ai" ? (
          <textarea
            ref={textRef}
            rows={1}
            value={question}
            onChange={(e) => onQuestionChange(e.target.value)}
            placeholder={
              llmEnabled
                ? "Ask a question about your data, in English or Hinglish"
                : "Add an API key to .env to ask in plain English, or switch to Write SQL"
            }
            disabled={!llmEnabled}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                if (canSubmit) onSubmit();
              }
            }}
            aria-label="Question"
            autoFocus
          />
        ) : (
          <div className="composer-editor">
            <SqlEditor
              key={props.resetKey}
              value={sql}
              onChange={onSqlChange}
              onRun={() => canSubmit && onSubmit()}
              dialect={props.dialect}
              schema={props.schema}
              theme={props.theme}
              minHeight="72px"
              maxHeight="240px"
              placeholder="SELECT * FROM … (Ctrl+Enter to run)"
              autoFocus
            />
          </div>
        )}
        {mode === "ai" && voiceSupported && llmEnabled && (
          <div className="voice">
            <button
              className="lang-btn"
              onClick={() => setLangIdx((i) => (i + 1) % VOICE_LANGS.length)}
              disabled={listening}
              title="Speaking language (click to switch between English and Hindi)"
              aria-label="Speaking language"
            >
              {VOICE_LANGS[langIdx].label}
            </button>
            <button
              className={"mic-btn" + (listening ? " listening" : "")}
              onClick={toggleVoice}
              aria-label={listening ? "Stop listening" : "Ask by voice"}
              title={listening ? "Stop listening" : "Ask by voice"}
            >
              {listening ? <MicOff size={17} /> : <Mic size={17} />}
            </button>
          </div>
        )}
        <button className="send-btn" onClick={onSubmit} disabled={!canSubmit} aria-label={mode === "ai" ? "Ask" : "Run"}>
          {busy ? <Loader2 size={18} className="spin" /> : <SendHorizontal size={18} />}
        </button>
      </div>
      <p className="composer-foot">
        {mode === "ai"
          ? "Enter to send · Shift+Enter for a new line · Queries are read-only"
          : "Ctrl+Enter to run · Only read-only SELECT queries are allowed"}
      </p>
    </div>
  );
}
