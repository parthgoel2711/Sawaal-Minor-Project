import { Activity, ArrowRight, BookOpen, Database, GraduationCap, LayoutDashboard, MessageSquare, Mic, Network, Plug, ShieldCheck, Upload } from "lucide-react";
import type { DatabaseInfo, View } from "../types";

interface Props {
  databases: DatabaseInfo[];
  llmEnabled: boolean;
  aiName: string;
  onOpenDb: (id: string) => void;
  onGo: (view: View) => void;
  onUpload: () => void;
}

const STEPS = [
  { n: "01", title: "Read the schema", text: "Tables, columns, keys and sample values are read from the database you pick." },
  { n: "02", title: "Write the SQL", text: "The model turns your question into one query, and repairs it if the database rejects it." },
  { n: "03", title: "Check it is read-only", text: "Every query is parsed first. Anything that could change data is refused." },
  { n: "04", title: "Run and explain", text: "You get the table, a chart, a plain-language summary and ideas for what to ask next." },
];

const MODULES: { view: View; icon: typeof MessageSquare; title: string; text: string }[] = [
  { view: "ask", icon: MessageSquare, title: "Ask", text: "English, Hinglish or voice in. SQL, table, chart and summary out." },
  { view: "documents", icon: BookOpen, title: "Documents", text: "Upload PDFs and ask about them. Answers cite the page they came from, and can mix in database numbers." },
  { view: "training", icon: GraduationCap, title: "Training", text: "Teach it your definitions and confirm good answers. It reuses them, so it gets more accurate on your data." },
  { view: "dashboard", icon: LayoutDashboard, title: "Dashboard", text: "Suggested charts for any database. Pin the ones you want and they re-run every time you open the page." },
  { view: "explore", icon: Network, title: "Explore", text: "Relationship diagram and a data-quality check for every table." },
  { view: "usage", icon: Activity, title: "Usage", text: "Questions per day, repairs needed and how long answers take." },
];

export function Home({ databases, llmEnabled, aiName, onOpenDb, onGo, onUpload }: Props) {
  return (
    <div className="home">
      <section className="home-hero">
        <div className="home-hero-text">
          <p className="home-kicker">Text to SQL</p>
          <h1>Ask your database in plain English</h1>
          <p className="home-sub">
            Sawaal reads your tables, writes the SQL, runs it read-only and shows the answer as a table, a chart and a
            sentence. Nobody has to know SQL to use it, and anyone who does can see and edit every query.
          </p>
          <div className="home-actions">
            <button className="primary-btn" onClick={() => onGo("ask")}>
              Start asking <ArrowRight size={16} />
            </button>
            <button className="ghost-btn" onClick={onUpload}>
              <Upload size={16} /> Upload your own data
            </button>
          </div>
          {!llmEnabled && <p className="home-note">AI is off until an API key is added to .env. SQL mode and Explore still work.</p>}
          {llmEnabled && <p className="home-note">Answers are written by {aiName}.</p>}
        </div>

        <figure className="specimen" aria-label="Example of an answer">
          <figcaption>Example</figcaption>
          <p className="specimen-q">Which department spends the most on salaries?</p>
          <pre className="specimen-sql">
            {`SELECT d.name, SUM(p.gross_pay) AS total
FROM payroll p
JOIN employees e USING (employee_id)
JOIN departments d USING (department_id)
GROUP BY d.name
ORDER BY total DESC
LIMIT 3`}
          </pre>
          <div className="specimen-answer">
            <p>Engineering has the largest payroll, well ahead of Sales and Operations.</p>
          </div>
          <table className="specimen-table">
            <tbody>
              <tr><td>Engineering</td><td className="num">1,24,60,000</td></tr>
              <tr><td>Sales</td><td className="num">78,35,000</td></tr>
              <tr><td>Operations</td><td className="num">61,90,000</td></tr>
            </tbody>
          </table>
        </figure>
      </section>

      <section className="home-section">
        <h2>How a question becomes an answer</h2>
        <ol className="home-steps">
          {STEPS.map((s) => (
            <li key={s.n}>
              <span className="home-step-n">{s.n}</span>
              <h3>{s.title}</h3>
              <p>{s.text}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="home-section">
        <h2>Pick a database</h2>
        <ul className="home-dbs">
          {databases.map((d) => (
            <li key={d.id}>
              <button onClick={() => onOpenDb(d.id)}>
                <Database size={16} />
                <span className="home-db-name">{d.name}</span>
                <span className="home-db-desc">{d.description || d.dialect}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="home-section">
        <h2>What is in the box</h2>
        <ul className="home-modules">
          {MODULES.map(({ view, icon: Icon, title, text }) => (
            <li key={view}>
              <button onClick={() => onGo(view)}>
                <Icon size={18} />
                <span className="home-module-title">{title}</span>
                <span className="home-module-text">{text}</span>
              </button>
            </li>
          ))}
          <li>
            <button onClick={onUpload}>
              <Plug size={18} />
              <span className="home-module-title">Connect</span>
              <span className="home-module-text">Point it at a live PostgreSQL or MySQL database. Read-only, with the password stored encrypted.</span>
            </button>
          </li>
          <li>
            <div className="home-module-static">
              <ShieldCheck size={18} />
              <span className="home-module-title">Safety</span>
              <span className="home-module-text">Roles with restricted tables, an audit log of every question, a read-only guard, hidden personal columns and a rate limit.</span>
            </div>
          </li>
          <li>
            <div className="home-module-static">
              <Mic size={18} />
              <span className="home-module-title">Voice</span>
              <span className="home-module-text">Speak a question in English or Hindi from the Ask page.</span>
            </div>
          </li>
        </ul>
      </section>

      <footer className="home-foot">React, FastAPI, SQLAlchemy and sqlglot. Claude or Groq writes the SQL.</footer>
    </div>
  );
}
