# Sawaal: viva preparation

Read this twice, then run the demo once yourself. Every team member should be able to answer sections 1 to 4 without notes.

## 1. The 30-second pitch

Sawaal lets anyone ask a database a question in plain English (or Hinglish, or by voice) and get back the answer as a sentence, a table and a chart, together with the exact SQL that produced it. An AI model writes the SQL, but our own code decides whether it is allowed to run: it must be a single read-only query, on tables the user may see, with a time limit and a row limit. If the database rejects the query, the error is sent back to the model and it fixes its own query. It also learns from corrections, has user roles and an audit log, answers questions about PDFs, and measures its own accuracy on a benchmark.

## 2. Problem and idea

- Data lives in relational databases. Getting answers needs SQL and knowledge of the table layout. Most people who ask the questions (managers, teachers, officials) cannot write SQL.
- Dashboards only answer questions someone planned in advance.
- Large language models (LLMs) can write SQL, but a naive "send the question to ChatGPT and run what comes back" approach has four problems:
  1. It invents table and column names (hallucination).
  2. It cannot recover when the database says "error".
  3. It is unsafe: it could run DROP or DELETE, leak personal data, or show tables the user should not see.
  4. Nobody can tell a right answer from a plausible wrong one.
- Our idea: **trust the model to be helpful, never to be safe.** Everything that must always be true is enforced by ordinary code around the model.

## 3. What it does (features)

| Feature | In one line |
| --- | --- |
| Ask | English, Hinglish or voice in; summary, table, chart, SQL and follow-up questions out |
| Self-repair | If the SQL fails, the error goes back to the model, up to 3 tries |
| Database routing | If you ask about customers while on the School database, it switches to the right database |
| Read-only guard | Only one SELECT is ever executed |
| Training | Teach confirmed examples and business rules; they are recalled for later questions |
| Roles | Viewer, analyst, admin; restricted tables are hidden and blocked for viewers |
| Audit log | Records every question, upload, login and denied request |
| Streaming | Shows the steps (reading schema, writing SQL, repairing) as they happen |
| Documents (RAG) | Upload PDFs, ask questions, answers cite the page |
| Dashboards | Suggested charts for any database; pin the ones you want |
| Connect | Live PostgreSQL and MySQL databases, password stored encrypted |
| Explore | Relationship (ER) diagram and a data-quality check |
| Evaluation | 29 benchmark questions with known-correct SQL; measures execution accuracy |
| Demo mode | Offline "Demo AI" so it can be presented without an API key |

## 4. How it works, step by step

Technology: **React 19 + TypeScript + Vite** frontend, **FastAPI (Python)** backend, **SQLAlchemy** for database access, **sqlglot** to parse SQL, **Claude or Groq** as the model, **SQLite** for the sample databases and our own small stores.

What happens when you type "How many students are there?":

1. **Browser to backend.** The page sends the question to `POST /api/generate/stream`. The reply comes back as Server-Sent Events (SSE), so progress appears live.
2. **Access check** (`main.py`, `auth.py`). A middleware reads the session cookie, finds the user and role, and checks the role is allowed for this endpoint. A login attempt is rate-limited.
3. **Routing** (`service.py`). If the chosen database does not hold the data, the model is shown a short catalogue of all databases and picks the right one.
4. **Schema** (`database.py`). SQLAlchemy reads the tables, columns, types, foreign keys, row counts and a few sample values, and writes them as compact `CREATE TABLE` text. This is what stops the model inventing names. For a viewer, restricted tables are left out here.
5. **Training recall** (`memory.py`). The question is matched against stored examples and rules using BM25 (keyword ranking). The 3 best examples and up to 8 rules are added to the prompt.
6. **Model writes SQL** (`llm.py`). The model returns structured output: `answerable`, `sql`, `explanation`. If the question cannot be answered from the data it says so.
7. **Guard** (`sql_guard.py`). sqlglot parses the SQL into a tree. We accept only one statement of type SELECT. We reject INSERT, UPDATE, DELETE, DROP, ATTACH, PRAGMA, SELECT INTO, multiple statements, and dangerous functions (pg_sleep, load_extension and others).
8. **Restricted tables** (`sql_guard.referenced_tables`, `database.execute`). We collect the real table names the query reads (excluding names defined by `WITH`) and refuse if a viewer touches a restricted one.
9. **Execute** (`database.py`). Read-only connection, 15-second timeout, 1,000-row cap.
10. **Repair loop.** If the database returns an error, the failed SQL and the error are sent back to the model, which writes a corrected query. At most 3 attempts.
11. **Mask personal data.** Columns whose names look like email, phone, Aadhaar or card numbers are hidden in the result.
12. **Insight** (`llm.py`). A second short model call writes the plain-language summary and 3 follow-up questions from the first rows.
13. **Answer streamed back.** The page shows the table, a chart chosen from the shape of the data, the SQL (editable) and the summary. The question is saved to history and, for admins, to the audit log.

### Why two layers of safety?
The guard is a parser, so it can be wrong about something unusual. The connection is also opened read-only, so even if a statement got past the guard the database itself would refuse to write. Two independent layers must both fail before data could change.

## 5. Key concepts you must be able to explain

- **Text-to-SQL / NLIDB:** translating a natural-language question into a database query.
- **LLM hallucination:** the model producing plausible but false output, such as a column that does not exist. Fixed here by giving it the real schema and by the repair loop.
- **Execution accuracy (EX):** a generated query is correct if it returns the same result as the reference ("gold") query, however it is written. Used by the Spider benchmark. Our comparison ignores row order and column order, tolerates rounding, and allows extra columns.
- **Spider and BIRD:** the standard academic Text-to-SQL benchmarks. Spider has multi-table databases across many domains; BIRD has large noisy databases.
- **sqlglot:** a Python SQL parser. It turns SQL text into a tree so we can inspect what the query really does instead of searching for keywords with regular expressions.
- **CTE (WITH clause):** a named temporary result inside a query. A viewer could try `WITH x AS (SELECT * FROM payroll) SELECT * FROM x`. We handle this because we look at the real tables, not at the alias `x`.
- **BM25:** a classic keyword ranking function used by search engines. It scores a document higher when it contains the rare query words. We use it to find similar taught examples and to find the best PDF passages.
- **RAG (retrieval-augmented generation):** fetch relevant text first, give it to the model, and tell it to answer only from that text. We use it for PDFs (with page citations) and for taught examples and rules.
- **SSE (Server-Sent Events):** the server keeps one HTTP response open and pushes events to the browser. Simpler than WebSockets for one-way progress updates.
- **scrypt:** a deliberately slow password-hashing function, so stolen hashes are hard to crack.
- **Fernet:** symmetric encryption from the `cryptography` library. We use it to store database connection strings.
- **HttpOnly cookie:** a cookie JavaScript cannot read, which protects the session from script injection.
- **Prompt injection:** hidden instructions in data that try to steer the model. Our protection is structural: the model can only produce SQL, and every SQL goes through the guard, so it cannot execute anything itself.
- **Few-shot examples:** showing the model a few solved examples inside the prompt. Our training memory is automatic few-shot selection.

## 6. What we built, and what we used

The whole application was written for this project; no existing Text-to-SQL framework is used. Our own code:

- the question pipeline (routing, schema, recall, generate, repair, insight);
- the read-only guard and restricted-table check;
- the schema reader and the read-only executor with timeout and row limit;
- training memory, roles, sessions, audit log, rate limiting, masking;
- documents (PDF passages and BM25 search), dashboard suggestions, database connections with encryption;
- the evaluation harness and 29-question benchmark, the offline Demo AI, streaming;
- the entire React interface (chat, SQL editor, charts, dashboard, ER diagram, admin pages).

Ordinary libraries we use, the way any project does: **FastAPI**, **SQLAlchemy**, **sqlglot** (SQL parser), **pypdf**, **cryptography**, **React**, **Recharts**, **CodeMirror**, and the **Claude or Groq API** for the language model. Only the model call is external; everything that decides what is safe is our code.

If the examiner asks whether similar tools exist, answer honestly: yes, other Text-to-SQL tools and academic systems exist; our report lists the main ones under related work. Ours is our own implementation, and what we emphasise is the safety layer, access control, measurement and the finished interface.

## 7. Honest limitations (say these before they ask)

- Accuracy depends on the model. A model can write a valid query that answers a slightly different question. We reduce this by showing the SQL, learning confirmed examples and measuring accuracy.
- **The live-model accuracy figure is not measured yet.** Our report shows the benchmark harness verified on all 29 questions using the scripted Demo AI. That proves the benchmark and executor work; it is not the accuracy of a language model. To get the real figure: `cd backend && python -m app.evaluate --delay 3` with an API key.
- The 29-question benchmark is small compared with Spider or BIRD.
- Demo AI only knows the prepared questions. It exists for presentation and offline testing, and the interface labels it.
- Masking is based on column names; an oddly named personal column would not be hidden.
- Document search is keyword-based, so different wording can miss a passage; scanned PDFs need OCR.
- The Vercel deployment keeps data in temporary storage, so it resets. Use the local version for real data.

## 8. How to demo (5 minutes)

Run `./start-demo.sh` (or open https://sawaal-minor-project.vercel.app). Sign in as `analyst` / `analyst-demo`.

1. Home page, then Ask. Choose School and click a suggested question. Point at the streamed steps, the SQL, the chart and the summary.
2. Type "how many customers do we have" while on School. It switches to E-commerce by itself (routing).
3. Type something unknown (for example a joke). It refuses instead of guessing.
4. Training: add a business rule, then use Teach on an answer.
5. Documents: upload a PDF, ask a question, show the page citation.
6. Dashboard: suggested charts, pin one.
7. Sign out, sign in as `viewer` / `viewer-demo`. Switch to Company and try to read `payroll` (SQL mode, `SELECT * FROM payroll`): refused. Sign in as the admin and show the Audit tab with the denied attempt.
8. Show the tests: `cd backend && ../.venv/bin/python -m pytest -q` (231 pass).

If asked to try a question live in demo mode that is not prepared, explain that Demo AI is a stand-in and show the real model by running locally with a Groq or Claude key.

## 9. Questions the examiner may ask, with answers

**Basics**

1. *What is your project?* See the 30-second pitch.
2. *Why is it useful?* Non-technical people get answers without waiting for an analyst, and everything stays safe and auditable.
3. *Which AI model do you use?* Anthropic Claude or Groq (free tier), chosen in `.env`. The code has a common interface, so a model can be swapped.
4. *Do you train a model?* No. We use a pre-trained model and improve it with prompt context: the schema, similar solved examples and business rules. The "training" page stores these; it does not change model weights.
5. *Which databases are supported?* SQLite (samples, uploads, CSV imports), PostgreSQL and MySQL.
6. *What languages can a user ask in?* English and Hinglish typed, English and Hindi by voice (the browser's speech recognition).

**Design and safety**

7. *Can it delete or change data?* No. One SELECT only, checked by a parser, and the connection is read-only as a second layer.
8. *Why a parser instead of blocking words like DELETE?* Keyword searching is easy to fool and gives false alarms (a column called "deleted_at"). A parser understands the structure.
9. *What if the model is tricked by text in the data?* The model only outputs SQL, and all SQL passes the guard. It cannot run commands.
10. *How do restricted tables work?* They are removed from the schema the viewer sees and from the prompt, and, separately, any query reading them is refused at execution using the parsed table names, including inside WITH clauses.
11. *How is personal data protected?* Columns that look like email, phone, Aadhaar or card numbers are masked; connection strings are encrypted; passwords are hashed with scrypt.
12. *What if the AI makes a mistake?* Three safeguards: the SQL is visible and editable, a database error triggers repair, and the benchmark measures accuracy.
13. *How does the repair loop work?* The failed query and the database's error message are returned to the model, which writes a corrected query. Up to three times.
14. *What is routing?* If the selected database does not contain the data, the model is shown a catalogue of databases and picks the one that does.
15. *Why Server-Sent Events?* One-way live updates over plain HTTP, simpler than WebSockets.

**Evaluation**

16. *How do you measure accuracy?* Execution accuracy on 29 questions with known-correct SQL across four databases (easy, medium, hard).
17. *What is your accuracy?* Be precise: the harness is verified (29 of 29 reference queries execute and match using the scripted Demo AI). The accuracy of a live model is run with `python -m app.evaluate` and depends on the model. Give the number if you have run it; do not make one up.
18. *Why not exact string match?* Two different SQL texts can mean the same thing; comparing results is fairer.
19. *How did you test it?* 231 automated tests (pytest) run offline using a scripted model, covering the guard (10 accepted, 22 refused queries), roles, restricted tables including the WITH bypass, audit, routing, repair, documents, memory and the API. Plus ruff, the TypeScript check and the production build.

**Features**

20. *How does the document feature work?* PDF text is split into passages of about 900 characters with page numbers, ranked with BM25 for the question, the best six go to the model, which must answer only from them and cite them by number.
21. *How does training memory work?* Confirmed question and SQL pairs and plain-English rules are stored per database. For each new question we rank them by BM25 and add the best ones to the prompt. Taught SQL must pass the guard first.
22. *How does dashboard suggestion work?* The model proposes charts from the schema; each query goes through the guard and is dropped if it fails or returns nothing. Without a model, rules over column types build the charts.
23. *How does connecting PostgreSQL work?* The user gives a URL; we test it, then store it encrypted. Only PostgreSQL and MySQL drivers are accepted because a SQLite URL could read any file on the server.
24. *What is Demo mode?* An offline stand-in for the model that returns the reference SQL for the prepared questions. It lets us present without an API key and is labelled "Demo AI".

**Comparison and honesty**

25. *Are there similar tools? What is different?* Yes, there are open-source and research systems. Ours differs in the parser-based guard plus read-only connection, restricted tables enforced on parsed SQL, audit log, documents, dashboards and a built-in benchmark, all in one finished application.
26. *What did you build yourselves?* Everything in section 6: the pipeline, guard, access control, memory, documents, dashboards, connections, evaluation and the interface. Only the language model and standard libraries are external.
27. *Why FastAPI?* Fast, typed, automatic validation with Pydantic, easy streaming.
28. *Why React and TypeScript?* Component-based interface, and types catch mistakes before running.
29. *What are the limitations?* Section 7.
30. *Future work?* Measured accuracy study with several models, embedding-based retrieval, schema pruning for wide databases, column-level permissions, production hardening, local models.

**Tricky ones**

31. *"Isn't this just ChatGPT with a database?"* No. The model is one component. The value is in what surrounds it: live schema grounding, a parser-based guard plus a read-only connection, repair, access control, audit and measurement.
32. *"What stops a viewer from asking for salaries in other words?"* The restriction is on tables, not on wording. Whatever SQL the model writes, reading a restricted table is refused.
33. *"Is the Vercel site safe to use for real data?"* No. It is a demonstration with temporary storage and shared demo logins. Real use is local or on a properly deployed server.
34. *"Your accuracy is 100%?"* No. 100% is the harness check with scripted answers. Do not present it as model accuracy.

## 10. Files to know

| File | Role |
| --- | --- |
| `backend/app/main.py` | FastAPI app: routes, middleware, streaming |
| `backend/app/service.py` | The question pipeline: route, recall, generate, repair, insight |
| `backend/app/llm.py` | Prompts and the Claude, Groq clients |
| `backend/app/sql_guard.py` | sqlglot read-only guard, referenced tables |
| `backend/app/database.py` | Schema reader and read-only executor |
| `backend/app/memory.py` | Training memory (examples, rules, BM25) |
| `backend/app/auth.py`, `audit.py` | Users, roles, sessions; audit log |
| `backend/app/documents.py` | PDF passages and BM25 search |
| `backend/app/autodash.py` | Dashboard suggestions |
| `backend/app/connections.py` | PostgreSQL and MySQL connections, encryption |
| `backend/app/evaluate.py`, `backend/eval/golden.json` | Benchmark harness and questions |
| `backend/app/demo.py` | Offline Demo AI |
| `frontend/src/App.tsx` and `components/` | The interface |

## 11. Suggested split for the team

Agree beforehand who answers what, so the examiner sees a team: one person on the idea, the problem and related work; one on the pipeline and safety; one on features (documents, training, dashboards, connections); one on evaluation, testing and deployment. Everyone should be able to run the demo and answer the basics.
