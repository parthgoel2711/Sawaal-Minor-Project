"""Draws the figures used in the project report. Run: ../.venv/bin/python report/make_figures.py"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse, FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).parent / "figures"
INK, MUTE, LINE, ACC, FILL = "#1f2430", "#5b6270", "#aab0bc", "#2b50c8", "#eef1f8"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9})


def canvas(w, h):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, w * 10)
    ax.set_ylim(0, h * 10)
    ax.axis("off")
    return fig, ax


def box(ax, x, y, w, h, text, fill=FILL, edge=LINE, bold=False, fs=8.5):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.2,rounding_size=1.2", fc=fill, ec=edge, lw=1))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, color=INK,
            fontweight="bold" if bold else "normal", linespacing=1.3)


def arrow(ax, a, b, text="", dashed=False, off=(0, 1.2)):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=10, lw=1.1, color=MUTE,
                                 linestyle="--" if dashed else "-"))
    if text:
        ax.text((a[0] + b[0]) / 2 + off[0], (a[1] + b[1]) / 2 + off[1], text, fontsize=7.5, color=MUTE, ha="center")


def save(fig, name):
    fig.savefig(OUT / name, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def architecture():
    fig, ax = canvas(6.6, 4.6)
    box(ax, 1, 33, 15, 9, "Browser\nReact + TypeScript\nvoice, charts, editor", bold=True, fs=7.5)
    box(ax, 23, 33, 19, 9, "FastAPI backend\nsign-in, roles, rate limit,\nstreaming (SSE)", bold=True, fill="#e3e9fb", edge=ACC, fs=7.5)
    box(ax, 50, 36, 15, 7, "AI model\nClaude / Groq / Demo", fs=7.5)
    box(ax, 50, 24, 15, 7, "SQL guard\nsqlglot, read-only", fs=7.5)
    box(ax, 50, 12.5, 15, 7, "Executor: timeout,\nrow cap, PII masking", fs=7.5)
    box(ax, 23, 17, 19, 8, "Training memory\nexamples + rules (BM25)", fs=7.5)
    box(ax, 23, 4, 19, 8, "Documents (RAG)\nPDF passages (BM25)", fs=7.5)
    box(ax, 1, 17, 15, 8, "Users, sessions\nAudit log\nHistory, usage", fs=7.5)
    box(ax, 50, 1, 15, 7, "Databases: sample,\nuploaded, PostgreSQL,\nMySQL", fill="#f3f3f3", fs=7.0)
    arrow(ax, (16.6, 37.5), (22.4, 37.5), "", off=(0, 1.2))
    ax.text(19.5, 39, "question", fontsize=7, color=MUTE, ha="center")
    arrow(ax, (42.6, 40.5), (49.4, 40.5))
    ax.text(46, 42, "schema", fontsize=7, color=MUTE, ha="center")
    arrow(ax, (49.4, 38), (42.6, 38))
    ax.text(46, 35.2, "SQL", fontsize=7, color=MUTE, ha="center")
    arrow(ax, (42.6, 34), (49.4, 28.5))
    arrow(ax, (57.5, 23.4), (57.5, 20.1))
    arrow(ax, (57.5, 11.9), (57.5, 8.6))
    arrow(ax, (32.5, 32.4), (32.5, 25.6))
    arrow(ax, (27, 32.4), (16.6, 25.6))
    arrow(ax, (32.5, 16.4), (32.5, 12.6))
    save(fig, "fig_4_1_architecture.png")


def workflow():
    fig, ax = canvas(7.6, 8.2)
    steps = ["Question typed or spoken", "Sign-in check, role, rate limit", "Pick the database (route if needed)",
             "Recall training: examples and rules", "AI writes one SQL query", "Guard: single read-only SELECT?",
             "Restricted tables for this role?", "Run read-only with timeout", "Mask personal columns",
             "Write summary and follow-ups", "Stream answer: table, chart, SQL"]
    y = 76
    ys = []
    for i, s in enumerate(steps):
        edge = ACC if i in (5, 6) else LINE
        box(ax, 8, y, 30, 4.4, s, edge=edge, fill="#e3e9fb" if i in (5, 6) else FILL, fs=8)
        ys.append(y)
        if i < len(steps) - 1:
            arrow(ax, (23, y - 0.3), (23, y - 2.9))
        y -= 7.0
    box(ax, 46, ys[7] - 5, 17, 7.5, "Repair: send the error\nback to the AI\n(at most 3 tries)", fill="#fdf1e3", edge="#d99a4e", fs=7.5)
    arrow(ax, (38.6, ys[7] + 2.2), (45.4, ys[7] - 1.2), "", dashed=True)
    ax.text(42, ys[7] + 1.6, "DB error", fontsize=7, color=MUTE, ha="center")
    ax.add_patch(FancyArrowPatch((63.6, ys[7] - 1.2), (38.6, ys[4] + 2.2), arrowstyle="-|>", mutation_scale=10, lw=1.1,
                                 color=MUTE, linestyle="--", connectionstyle="arc3,rad=0.55"))
    ax.text(72, ys[5] - 3, "new SQL", fontsize=7, color=MUTE, ha="center")
    box(ax, 46, ys[6] + 2.5, 17, 7.5, "Not allowed: refuse\nand write to\nthe audit log", fill="#fbe9e9", edge="#cc6a6a", fs=7.5)
    arrow(ax, (38.6, ys[6] + 2.2), (45.4, ys[6] + 5.5), "", dashed=True)
    ax.text(41.5, ys[6] + 5.6, "no", fontsize=7, color=MUTE, ha="center")
    save(fig, "fig_4_2_workflow.png")


def usecase():
    fig, ax = canvas(8.0, 5.0)
    ax.add_patch(plt.Rectangle((18, 2), 40, 46, fill=False, ec=LINE, lw=1))
    ax.text(38, 49, "Sawaal", ha="center", fontsize=9, color=MUTE)
    cases = ["Ask a question", "View table, chart, SQL", "Teach examples and rules", "Upload files and PDFs",
             "Connect PostgreSQL / MySQL", "Pin dashboard charts", "Manage users", "Read audit log"]
    ys = [43, 37.5, 32, 26.5, 21, 15.5, 10, 4.5]
    for c, y in zip(cases, ys):
        ax.add_patch(Ellipse((38, y), 30, 4.6, fc=FILL, ec=LINE))
        ax.text(38, y, c, ha="center", va="center", fontsize=8, color=INK)
    actors = {"Viewer": (6, 38), "Analyst": (6, 24), "Admin": (6, 10), "AI model": (70, 38)}
    for name, (x, y) in actors.items():
        ax.plot([x], [y + 3], "o", ms=7, color=INK)
        ax.plot([x, x], [y + 2.5, y - 1.5], color=INK, lw=1.3)
        ax.plot([x - 2, x + 2], [y + 1, y + 1], color=INK, lw=1.3)
        ax.plot([x, x - 2], [y - 1.5, y - 4], color=INK, lw=1.3)
        ax.plot([x, x + 2], [y - 1.5, y - 4], color=INK, lw=1.3)
        ax.text(x, y - 6.5, name, ha="center", fontsize=8.5, color=INK)
    links = [("Viewer", [0, 1]), ("Analyst", [0, 1, 2, 3, 5]), ("Admin", [4, 6, 7]), ("AI model", [0])]
    for a, idx in links:
        x, y = actors[a]
        for i in idx:
            tx = 23 if a != "AI model" else 53
            ax.plot([x + (2 if a != "AI model" else -2), tx], [y, ys[i]], color=LINE, lw=0.8)
    save(fig, "fig_4_3_usecase.png")


def sequence():
    fig, ax = canvas(8.0, 5.4)
    names = ["User", "Browser", "FastAPI", "AI model", "Database"]
    xs = [6, 22, 38, 54, 69]
    for n, x in zip(names, xs):
        box(ax, x - 6, 47, 12, 4.5, n, bold=True)
        ax.plot([x, x], [4, 47], color=LINE, lw=1, ls=(0, (4, 3)))
    msgs = [(0, 1, 43, "types question"), (1, 2, 39.5, "POST /api/generate/stream"),
            (2, 2, 36, "check role, load schema + memory"), (2, 3, 32.5, "schema, hints, question"),
            (3, 2, 29, "SQL"), (2, 2, 25.5, "guard: read-only? tables allowed?"),
            (2, 4, 22, "run SELECT"), (4, 2, 18.5, "rows (or error: repair loop)"),
            (2, 3, 15, "rows for summary"), (3, 2, 11.5, "summary + follow-ups"),
            (2, 1, 8, "events: status, sql, done"), (1, 0, 4.5, "table, chart, answer")]
    for a, b, y, t in msgs:
        if a == b:
            ax.add_patch(FancyBboxPatch((xs[a] + 0.8, y - 1.2), 14, 2.4, boxstyle="round,pad=0.1", fc="#fdf6e3", ec=LINE, lw=0.7))
            ax.text(xs[a] + 1.4, y, t, fontsize=7, va="center", color=INK)
        else:
            arrow(ax, (xs[a], y), (xs[b], y))
            ax.text((xs[a] + xs[b]) / 2, y + 0.9, t, fontsize=7.2, ha="center", color=MUTE)
    save(fig, "fig_4_4_sequence.png")


def er():
    fig, ax = canvas(7.4, 5.2)
    tables = {
        "customers": (4, 38, ["customer_id PK", "first_name, last_name", "email, city, state", "segment, signup_date"]),
        "orders": (27, 38, ["order_id PK", "customer_id FK", "employee_id FK", "order_date, status"]),
        "employees": (50, 38, ["employee_id PK", "manager_id FK (self)", "title, region", "hire_date, salary"]),
        "order_items": (27, 16, ["order_item_id PK", "order_id FK", "product_id FK", "quantity, unit_price"]),
        "products": (4, 16, ["product_id PK", "category_id FK", "name, price, cost", "stock_quantity"]),
        "categories": (4, 0.5, ["category_id PK", "name, description"]),
        "reviews": (50, 16, ["review_id PK", "product_id FK", "customer_id FK", "rating, review_date"]),
    }
    pos = {}
    for n, (x, y, cols) in tables.items():
        h = 3 + 2.6 * len(cols)
        ax.add_patch(plt.Rectangle((x, y), 19, h, fc="white", ec=LINE, lw=1))
        ax.add_patch(plt.Rectangle((x, y + h - 3), 19, 3, fc="#e3e9fb", ec=LINE, lw=1))
        ax.text(x + 9.5, y + h - 1.5, n, ha="center", va="center", fontweight="bold", fontsize=8.5, color=INK)
        for i, c in enumerate(cols):
            ax.text(x + 1, y + h - 5.2 - 2.6 * i, c, fontsize=7.2, va="center", color=INK)
        pos[n] = (x, y, h)

    def link(a, b, sa="r", sb="l", cs="arc3,rad=0"):
        xa, ya, ha = pos[a]; xb, yb, hb = pos[b]
        pa = (xa + (19 if sa == "r" else 0 if sa == "l" else 9.5), ya + (ha / 2 if sa in "rl" else (ha if sa == "t" else 0)))
        pb = (xb + (19 if sb == "r" else 0 if sb == "l" else 9.5), yb + (hb / 2 if sb in "rl" else (hb if sb == "t" else 0)))
        ax.add_patch(FancyArrowPatch(pa, pb, arrowstyle="-|>", mutation_scale=8, lw=1, color=MUTE, connectionstyle=cs))

    link("orders", "customers", "l", "r"); link("employees", "orders", "l", "r")
    link("order_items", "orders", "t", "b"); link("order_items", "products", "l", "r")
    link("products", "categories", "b", "t"); link("reviews", "products", "b", "b", "arc3,rad=-0.25")
    save(fig, "fig_5_1_er.png")


def bars_benchmark():
    fig, ax = plt.subplots(figsize=(6.2, 3.0))
    dbs = ["E-commerce", "Company", "Government", "School"]
    easy, med, hard = [3, 2, 2, 2], [3, 3, 3, 3], [3, 2, 2, 1]
    ax.barh(dbs, easy, color="#c9d3f0", label="Easy")
    ax.barh(dbs, med, left=easy, color="#7e96e0", label="Medium")
    ax.barh(dbs, hard, left=[a + b for a, b in zip(easy, med)], color=ACC, label="Hard")
    ax.invert_yaxis()
    ax.set_xlabel("Benchmark questions")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.legend(frameon=False, loc="lower right")
    save(fig, "fig_6_1_benchmark.png")


def bars_tests():
    data = [("API", 19), ("Auth and roles", 17), ("Database", 15), ("Groq client", 12), ("Documents", 12),
            ("Training memory", 10), ("LLM prompts", 9), ("Connections", 9), ("Masking, profile, stats", 8),
            ("Routing", 7), ("Insight", 7), ("Evaluation", 7), ("Importer", 5), ("Explain", 5), ("Dashboards", 5),
            ("Demo AI", 4), ("Rate limit", 3), ("SQL guard", 2)]
    fig, ax = plt.subplots(figsize=(6.2, 4.0))
    ax.barh([d[0] for d in data], [d[1] for d in data], color=ACC)
    ax.invert_yaxis()
    ax.set_xlabel("Test functions (parametrised cases bring the total to 231)")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    save(fig, "fig_6_2_tests.png")


for f in (architecture, workflow, usecase, sequence, er, bars_benchmark, bars_tests):
    f()
print("done")
