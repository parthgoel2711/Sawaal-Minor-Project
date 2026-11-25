# Presenting Sawaal

## Start
Run `./start-demo.sh` (Windows: `start-demo.bat`). No API key or internet is needed.
The page shows a sign-in. Accounts: `admin / admin-demo`, `analyst / analyst-demo`, `viewer / viewer-demo`.
The header says "Demo AI": it answers the 29 prepared benchmark questions. Say so at the start; it is honest and it
keeps the demo reliable. For live AI, run `./start.sh` with a Claude or Groq key instead.

## Slide outline (10 minutes)
1. Problem: most people cannot write SQL, so data waits for an analyst.
2. Idea: ask in English, Hinglish or voice. See the SQL, the table, a chart and a sentence.
3. Pipeline: read schema, write SQL, check it is read-only, run, repair on error, explain.
4. What we added on top of the original: documents (RAG), suggested dashboards, PostgreSQL/MySQL connections.
5. What we adopted from Vanna 2.0: training memory, roles and restricted tables, audit log, streaming.
6. Safety: sqlglot guard plus a read-only connection, PII masking, rate limit, encrypted connection strings.
7. Evaluation: 29 questions on 4 databases, graded by result match (`backend/eval`).
8. Limits and future work.

## Live script
1. Sign in as `analyst`. Home page, then Ask on the School database.
2. Pick a suggested question. Point out the streamed steps, the SQL, the chart and the summary.
3. Ask "how many customers do we have" while on School: it routes to the right database by itself.
4. Type something unknown: it refuses instead of guessing.
5. Training page: add a business rule. Explain that examples and rules are recalled for later questions.
6. Documents: upload a PDF and ask about it; the answer cites the page.
7. Dashboard: suggested charts, pin one.
8. Sign out, sign in as `viewer`. Open Company and ask about payroll: refused. The admin's Audit tab shows the attempt.
9. Sign in as `admin`: Admin, Audit and Users.

## Compared with Vanna 2.0
| | Vanna 2.0 | Sawaal |
| --- | --- | --- |
| Shape | Python framework you build an app on | Finished app: UI, API, auth, history |
| Memory | Agent memory, tools | Training page with examples and rules |
| Permissions | User groups on tools | Roles plus restricted tables enforced on the SQL |
| Extras | Streaming, audit | Streaming, audit, documents, dashboards, ER diagram, data quality, voice |

## Questions to expect
- Is Demo AI cheating? It is a prepared stand-in; the guard, execution, charts, roles and audit are real. Live mode uses Claude or Groq.
- Can it change data? No: one SELECT only, and the connection itself is read-only.
- How do you measure accuracy? `python -m app.evaluate` runs the benchmark against the generator.
