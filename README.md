# Sawaal

**Ask your data in plain English.** Sawaal turns a question into SQL, runs it safely, and explains the answer.

Ask questions about your data in plain English and get the answer as a table or a chart.
An AI model writes the SQL ([Claude](https://www.anthropic.com/claude), or a free model through
[Groq](https://console.groq.com/)), the app checks that it only reads data, runs it, and fixes the query by itself
if the database returns an error.

It's a website that runs on your computer: start it and open **http://localhost:8000** in Chrome (or any browser).

## Features

- **Chat with documents.** Upload PDFs or text files and ask questions about them. Answers cite the passages
  (and page numbers) they came from. Pick a database too and the answer can combine document text with live numbers.
  Retrieval is BM25, so it needs no embedding model and works offline; without an AI key you still get the best passages.
- **Suggested dashboards.** One click proposes six charts for any database (AI-written when a key is set, otherwise
  built from the column types). Pin the ones you want.
- **Connect real databases.** Add a PostgreSQL or MySQL database from the app. Connections run read-only and the
  connection string is stored encrypted.
- **Command palette.** Press **Ctrl/Cmd+K** to jump between pages, switch databases or run an example question.
- **Explain this SQL.** One click turns any query into a step-by-step explanation in plain words, which is useful
  for learning SQL.
- **Reports.** Download a whole conversation (questions, answers, SQL and the first rows of each result) as one
  self-contained HTML page, ready to print to PDF. Results also copy as Markdown tables.

- **Plain-English questions → SQL.** Follow-up questions ("now only for Mumbai") use the conversation so far.
- **Finds the right database.** Ask about students while the E-commerce database is selected, and the app answers
  from the School database instead, telling you where the answer came from.
- **Self-correcting.** If a query fails, the AI sees the error and repairs it (up to 3 times by default).
- **Free or paid AI.** Use Claude for the best answers, or Groq's free tier at no cost.
- **Read-only by design.** Only single `SELECT` queries are allowed, the database connection itself is read-only,
  queries time out after 15 seconds and results are capped at 1,000 rows.
- **Answers in plain words.** Besides the table, the AI writes a short summary of what the result means and
  suggests three follow-up questions you can click.
- **Dashboard.** Pin any answer; the Dashboard page re-runs all pinned queries live and shows them as charts.
- **Explore your data.** An entity-relationship diagram drawn from the foreign keys, and a data-quality report
  (empty values, distinct counts, ranges, constant or mostly-empty columns) for every table. No AI needed.
- **Usage page.** Questions per day, success rate, how often the AI repaired its own query, and average answer time.
- **Privacy by default.** Columns that look like personal data (email, phone, password, Aadhaar, card numbers...)
  are hidden in every result. Turn it off with `MASK_PII=false`.
- **Voice questions.** Click the microphone and ask in English or Hindi (Chrome, Edge and Safari).
- **Measurable accuracy.** A built-in benchmark of 29 questions with known-correct SQL reports how often the AI is
  right (see [Measuring accuracy](#measuring-accuracy)).
- **Editable SQL.** Every answer shows the SQL in an editor with highlighting and autocomplete. Change it and press Run.
- **Write SQL yourself.** Switch to *Write SQL* mode; this works even without an API key.
- **Tables and charts.** Sortable, paginated results, automatic bar/line charts, and CSV download.
- **Bring your own data.** Upload CSV files (each becomes a table) or SQLite databases, or connect PostgreSQL/MySQL.
- **Schema browser** with tables, columns, keys, relationships and one-click previews.
- **History** of every question and query, with stars for the ones you want to keep.
- **Light and dark themes**, works on phones too.
- Ships with **four sample databases** so you can try it immediately:
  - **E-commerce**: customers, products, orders, employees and reviews (prices in INR)
  - **School**: students, classes, subjects, teachers, exam marks and monthly attendance for 2025-26
  - **Company**: a fictional IT company's employees, departments, salaries and payroll, projects, leaves and reviews
  - **Government**: Indian states and districts, welfare scheme budgets, hospitals and citizen grievances
    (practice data: figures are approximate or synthetic, **not official statistics**)

## Presenting it

`./start-demo.sh` (or `start-demo.bat`) runs Sawaal with no API key. A built-in "Demo AI" answers the 29 benchmark
questions with their known-correct SQL, and sign-in plus restricted tables are switched on. Everything else (guard,
execution, charts, training, roles, audit, streaming) is the real code. Accounts: `admin / admin-demo`,
`analyst / analyst-demo`, `viewer / viewer-demo`. The step-by-step script is in [PRESENTATION.md](PRESENTATION.md).

## Quick start

You need **Python 3.11+** and **Node.js 20+**, plus one API key:

| Provider | Cost | Get a key | Put in `.env` |
| --- | --- | --- | --- |
| **Groq** | Free tier (rate-limited) | [console.groq.com/keys](https://console.groq.com/keys) | `GROQ_API_KEY=...` |
| **Claude** | Paid, best quality | [console.anthropic.com](https://console.anthropic.com/) | `ANTHROPIC_API_KEY=...` |

If both keys are set, Claude is used; add `LLM_PROVIDER=groq` to use Groq instead.

### Windows (one click)

Double-click **`start.bat`** (or run it from a terminal). The first run installs everything, builds the website,
creates a `.env` file, and opens the app in your browser. Paste your key into `.env` and run `start.bat` again.

### macOS / Linux

```bash
./start.sh
```

### Manual setup

```bash
# 1. Python backend
python -m venv .venv
.venv\Scripts\activate            # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r backend/requirements.txt

# 2. Your API key
copy .env.example .env            # macOS/Linux: cp .env.example .env
# then edit .env and set ANTHROPIC_API_KEY=...

# 3. Build the website
cd frontend
npm install
npm run build
cd ..

# 4. Run
cd backend
python -m app
```

Open **http://localhost:8000**.

### Docker

```bash
cp .env.example .env              # add your key
docker compose up --build
```

Open **http://localhost:8000**. Uploaded files and history are kept in `./data`.

## Using your own data

- **CSV files:** click **Upload data** and pick a `.csv` (comma, semicolon, tab or pipe separated). Column types
  (whole numbers, decimals, text) are detected automatically. You can add more CSVs to the same database as extra tables,
  so you can ask questions that join them.
- **SQLite databases:** upload a `.db`, `.sqlite` or `.sqlite3` file.
- **PostgreSQL / MySQL from the app:** click **Add data**, choose **Connect a database**, give it a name and a URL such as
  `postgresql://readonly:password@host:5432/analytics` or `mysql://user:password@host/dbname`. The connection is tested,
  then stored encrypted in `data/connections.json` (key in `data/.connection_key`, owner-only). Remove it with the
  trash button next to the database picker.
- **PostgreSQL / MySQL from `.env`:** the same drivers are installed by `requirements.txt`; add the
  connection to `.env`:

  ```ini
  DATABASES=analytics=postgresql+psycopg://readonly:password@localhost:5432/analytics
  ```

  Several databases are separated by `;`. **Use a database user that can only read.** The app also runs every query
  in a read-only transaction, but a read-only user is the real guarantee.

## Configuration

All settings go in `.env` (see [`.env.example`](.env.example)).

| Variable | Default | What it does |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | – | Claude API key (paid). |
| `GROQ_API_KEY` | – | Groq API key (free tier). Without any key, only *Write SQL* mode works. |
| `LLM_PROVIDER` | `auto` | `auto` (Claude if its key is set, else Groq), `anthropic`, or `groq`. |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Groq model used to write SQL. |
| `GROQ_FALLBACK_MODEL` | `openai/gpt-oss-20b` | Used right away when the main Groq model hits its free-tier limit. |
| `AUTO_ROUTE` | `true` | Answer from another database when the selected one doesn't have the data. |
| `CLAUDE_MODEL` | `claude-opus-5-5` | Claude model used to write SQL. |
| `CLAUDE_EFFORT` | `medium` | How hard Claude thinks: `low`, `medium`, `high`, `xhigh`, `max`. Higher is slower but better on hard questions. |
| `CLAUDE_FALLBACKS` | `true` | If the model declines a request, retry on a fallback model automatically. |
| `RATE_LIMIT_PER_MINUTE` | `30` | Plain-English questions allowed per client per minute (`0` = no limit). Protects your AI quota. |
| `MASK_PII` | `true` | Hide values in columns that look like personal data. |
| `MAX_FIX_ATTEMPTS` | `3` | How many times the AI may repair a failing query. |
| `MAX_ROWS` | `1000` | Most rows returned per query. |
| `QUERY_TIMEOUT_SECONDS` | `15` | Queries running longer are stopped. |
| `MAX_UPLOAD_MB` | `50` | Largest file you can upload. |
| `DATABASES` | – | Extra databases: `name=sqlalchemy_url;name2=url2`. |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Where the server listens. |

## How it works

```
Browser (React)  ──question──▶  FastAPI  ──schema + question──▶  Claude or Groq
                                   │  ◀────── JSON {sql, explanation} ──┘
                                   ▼
                          SQL safety check (sqlglot)
                                   ▼
                     Read-only connection, timeout, row limit
                                   │
                    error? ── send error back to Claude, retry
                                   ▼
                  Browser shows explanation, SQL, table, chart
```

1. The backend reads the database schema: tables, columns, keys, row counts, a few sample rows, and the values of
   short categorical columns (like order `status`). This goes into the prompt so Claude uses exact names and values.
2. Claude replies in a fixed JSON format (structured outputs): whether the question can be answered, the SQL, and a
   short plain-language explanation. The schema part of the prompt is cached, so repeat questions are cheaper.
3. The SQL is parsed with [sqlglot](https://github.com/tobymao/sqlglot). Anything other than a single read query is
   rejected (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ATTACH`, `PRAGMA`, `SELECT ... INTO`, multiple statements, and
   functions like `load_extension` or `pg_sleep`).
4. The query runs on a **read-only** connection (SQLite opens files with `mode=ro` and `query_only`; PostgreSQL and
   MySQL use read-only transactions), with a timeout and a row limit.
5. If the database reports an error, the error goes back to the AI, which writes a corrected query.
6. After a successful answer, a second small AI call reads the first rows of the result and writes a plain-language
   summary plus three follow-up questions. If that call fails, the answer is still shown without it.
7. If the selected database doesn't have the data, the AI is shown a short list of every database's tables and
   picks the one that does; the question is answered there and the answer says which database it came from.

## Measuring accuracy

An AI that writes SQL is only useful if you know how often it is right. The repository ships with a benchmark of
29 questions (easy, medium and hard) over the four sample databases, each with a known-correct SQL query
([`backend/eval/golden.json`](backend/eval/golden.json)). The metric is **execution accuracy**, as in the Spider
benchmark: an answer counts as correct when it returns the same data as the correct query, however the SQL is
written. Row order, column order and small rounding differences are ignored.

```bash
cd backend
python -m app.evaluate                        # all questions (needs an API key)
python -m app.evaluate --db school            # one database
python -m app.evaluate --difficulty hard --delay 3   # slow down for free-tier limits
```

It prints PASS/FAIL per question and saves a Markdown and JSON report (accuracy overall, by difficulty and by
database, how many were right on the first try, wrong answers with their SQL) to `data/eval/`. Use it to compare
models (`GROQ_MODEL`, `CLAUDE_MODEL`) or to check that a prompt change did not make things worse.

## Project structure

```
backend/
  app/
    main.py        API routes; also serves the built website
    llm.py         prompt, Claude and Groq clients, JSON answers, error handling
    service.py     question → SQL → result pipeline with auto-repair, routing and insights
    evaluate.py    accuracy benchmark (python -m app.evaluate)
    ratelimit.py   per-client limit on AI questions
    database.py    database registry, schema reading, read-only execution, uploads
    sql_guard.py   read-only SQL validation
    importer.py    CSV → SQLite import with type detection
    history.py     query history (stored in data/app.db)
    seed.py        builds the sample e-commerce database (and lists all samples)
    seed_school.py, seed_company.py, seed_government.py   the other sample databases
    config.py      settings from .env
  eval/golden.json   benchmark questions with correct SQL
  tests/           pytest suite (no API key needed; Claude is mocked)
frontend/
  src/
    App.tsx        page layout and state
    components/    composer (with voice input), answer cards, dashboard, ER diagram, data-quality and usage pages, SQL editor, table, chart, schema, history, upload
    lib/           chart detection, formatting, CSV export
docs/              screenshots
start.bat / start.sh   one-command setup and start
Dockerfile, docker-compose.yml
```

## Development

Run the backend and the website dev server separately to get hot reload:

```bash
# terminal 1
cd backend
RELOAD=1 python -m app          # Windows PowerShell: $env:RELOAD=1; python -m app

# terminal 2
cd frontend
npm run dev                     # opens on http://localhost:5173 and forwards /api to :8000
```

Tests and checks:

```bash
cd backend
pip install -r requirements-dev.txt
pytest                          # 170+ tests: SQL safety, schemas, CSV import, API, routing, insights, benchmark, Claude + Groq requests
ruff check .

cd ../frontend
npm run build                   # type-checks and builds
```

GitHub Actions runs the same checks on every push and pull request.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Status, whether AI is enabled, model name |
| `GET` | `/api/databases` | List databases |
| `GET` | `/api/databases/{id}/schema` | Tables, columns, keys, row counts |
| `GET` | `/api/databases/{id}/examples` | Example questions |
| `POST` | `/api/databases/upload` | Upload a CSV or SQLite file (`file`, optional `database_id` to add a table) |
| `POST` | `/api/databases/connect` | `{name, url}` → connect a PostgreSQL/MySQL database |
| `DELETE` | `/api/databases/{id}` | Delete an uploaded or connected database |
| `POST` | `/api/databases/{id}/auto-dashboard` | Suggest charts for a database |
| `GET` / `POST` / `DELETE` | `/api/documents[/{id}]` | List, upload (PDF/TXT/MD/CSV) and delete documents |
| `POST` | `/api/documents/ask` | `{question, document_ids?, database_id?}` → cited answer and sources |
| `POST` | `/api/generate` | `{database_id, question, history?, insights?}` → SQL, explanation, result, summary, follow-up questions |
| `GET` | `/api/databases/{id}/profile` | Data-quality profile of every table |
| `GET` | `/api/stats` | Usage statistics from history (`?database_id=`) |
| `POST` | `/api/explain` | `{database_id, sql}` → plain-language summary and steps |
| `POST` | `/api/execute` | `{database_id, sql}` → result |
| `GET` / `PATCH` / `DELETE` | `/api/history[/{id}]` | List, star, delete history |

Interactive API docs are at **http://localhost:8000/docs** while the server is running.

## Before putting it on the internet

The app has no login. Anyone who can open it can ask questions (which uses your API credits or free quota), upload files,
and read every connected database. Run it on your own machine or a private network, or put it behind a login
(for example a reverse proxy with authentication) before exposing it publicly.

## License

[MIT](LICENSE)
