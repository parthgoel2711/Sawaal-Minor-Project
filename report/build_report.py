"""Builds the minor project report as a Word file.

Run from the project root:  .venv/bin/python report/build_report.py
Output: report/Sawaal_Minor_Project_Report.docx
"""

from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

HERE = Path(__file__).parent
FIG = HERE / "figures"
OUT = HERE / "Sawaal_Minor_Project_Report.docx"

TITLE = "Sawaal: Ask Your Database in Plain English"
TEAM = [
    ("Parth Goel", "36017711923"),
    ("Sagar Kaushik", "35417711923"),
    ("Antriksh Kumar", "60317711924"),
    ("Deepanshu Swami", "6071770824"),
]
SUPERVISOR = "Dr. Shivanka"

doc = Document()

# ---------------------------------------------------------------- base styles
normal = doc.styles["Normal"]
normal.font.name = "Times New Roman"
normal.font.size = Pt(12)
normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
normal.paragraph_format.space_after = Pt(6)
normal.paragraph_format.line_spacing = 1.15


def style_heading(name, size, before, after):
    st = doc.styles[name]
    st.font.name = "Times New Roman"
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
    st.font.size = Pt(size)
    st.font.bold = True
    st.font.italic = False
    st.font.color.rgb = RGBColor(0, 0, 0)
    st.paragraph_format.space_before = Pt(before)
    st.paragraph_format.space_after = Pt(after)
    st.paragraph_format.keep_with_next = True


style_heading("Heading 1", 18, 0, 14)
style_heading("Heading 2", 14, 14, 6)
style_heading("Heading 3", 12, 10, 4)

for cap in ("Figure Caption", "Table Caption"):
    st = doc.styles.add_style(cap, 1)
    st.base_style = doc.styles["Normal"]
    st.font.size = Pt(11)
    st.font.bold = True
    st.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    st.paragraph_format.space_before = Pt(4)
    st.paragraph_format.space_after = Pt(12)
doc.styles["Table Caption"].paragraph_format.keep_with_next = False

page = doc.sections[0]
page.page_width, page.page_height = Inches(8.27), Inches(11.69)  # A4
for side in ("left_margin", "right_margin"):
    setattr(page, side, Inches(1.1))
page.top_margin = page.bottom_margin = Inches(1)


# ---------------------------------------------------------------- helpers
def para(text="", bold=False, italic=False, align=None, size=None, after=None, before=None, style=None):
    p = doc.add_paragraph(style=style)
    if text:
        r = p.add_run(text)
        r.bold, r.italic = bold, italic
        if size:
            r.font.size = Pt(size)
    if align == "center":
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    elif align == "justify":
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    if after is not None:
        p.paragraph_format.space_after = Pt(after)
    if before is not None:
        p.paragraph_format.space_before = Pt(before)
    return p


def body(text):
    return para(text, align="justify")


def rich(parts):
    """Paragraph from [(text, bold)] parts."""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    for text, bold in parts:
        p.add_run(text).bold = bold
    return p


def bullet(text, lead=None):
    p = doc.add_paragraph(style="List Bullet")
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    if lead:
        p.add_run(lead).bold = True
    p.add_run(text)
    p.paragraph_format.space_after = Pt(3)
    return p


def h1(text):
    return doc.add_heading(text, level=1)


def h2(text):
    return doc.add_heading(text, level=2)


def page_break():
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def shade(cell, color):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), color)
    tc_pr.append(shd)


def table(headers, rows, widths=None, highlight_blank=False):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        c = t.rows[0].cells[i]
        c.text = ""
        r = c.paragraphs[0].add_run(h)
        r.bold = True
        r.font.size = Pt(10.5)
        shade(c, "E7E9EE")
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            run = cells[i].paragraphs[0].add_run(str(v))
            run.font.size = Pt(10.5)
            if highlight_blank and str(v).startswith("__"):
                cells[i].paragraphs[0].runs[0].text = "          "
                shade(cells[i], "FFF2A8")
    for row in t.rows:
        for c in row.cells:
            for p in c.paragraphs:
                p.paragraph_format.space_after = Pt(2)
                p.paragraph_format.line_spacing = 1.0
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Inches(w)
    return t


def caption(kind, text):
    return doc.add_paragraph(text, style=f"{kind} Caption")


def figure(file, cap, width=5.6):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.keep_with_next = True
    p.add_run().add_picture(str(FIG / file), width=Inches(width))
    caption("Figure", cap)


def field(paragraph, instr, placeholder=""):
    """Insert a Word field (page numbers, tables of contents)."""
    for kind in ("begin", None, "separate", "text", "end"):
        run = paragraph.add_run()
        if kind == "begin":
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), "begin")
            el.set(qn("w:dirty"), "true")
            run._r.append(el)
        elif kind is None:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = instr
            run._r.append(el)
        elif kind == "separate":
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), "separate")
            run._r.append(el)
        elif kind == "text":
            run.text = placeholder
        else:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), "end")
            run._r.append(el)


def footer_page_number(section, fmt, start=None):
    section.footer.is_linked_to_previous = False
    for p in section.footer.paragraphs:
        p.text = ""
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    field(p, "PAGE", "1")
    sect_pr = section._sectPr
    for old in sect_pr.findall(qn("w:pgNumType")):
        sect_pr.remove(old)
    pg = OxmlElement("w:pgNumType")
    pg.set(qn("w:fmt"), fmt)
    if start is not None:
        pg.set(qn("w:start"), str(start))
    sect_pr.append(pg)


def blank_footer(section):
    section.footer.is_linked_to_previous = False
    for p in section.footer.paragraphs:
        p.text = ""


def new_section():
    s = doc.add_section(WD_SECTION.NEW_PAGE)
    return s


def signature_block():
    for name, roll in TEAM:
        para("Signature: ___________________________", before=14, after=0)
        para(f"{name} ({roll})", after=0)


# ================================================================ COVER
for _ in range(2):
    para("")
para("Minor Project Report", bold=True, align="center", size=22, after=18)
para(f"“{TITLE}”", bold=True, align="center", size=16, after=24)
para("Under the Guidance of", align="center", size=13, after=4)
para(SUPERVISOR, bold=True, align="center", size=14, after=24)
para("Submitted By:", bold=True, align="center", size=13, after=4)
for name, roll in TEAM:
    para(f"{name}, {roll}, AI & DS – Section B", align="center", size=13, after=2)
para("", after=20)
para("Department of Artificial Intelligence and Data Science", bold=True, align="center", size=13, after=2)
para("Vivekananda School of Engineering and Technology (VSET)", align="center", size=13, after=2)
para("Vivekananda Institute of Professional Studies – Technical Campus (VIPS-TC)", align="center", size=13, after=2)
para("Pitampura, Delhi – 110034", align="center", size=13, after=2)
para("Affiliated to Guru Gobind Singh Indraprastha University (GGSIPU), Dwarka, Delhi", align="center", size=13, after=2)
para("(7th Semester, Academic Year 2026–27)", align="center", size=13)
blank_footer(doc.sections[0])

# ================================================================ FRONT MATTER
s = new_section()
footer_page_number(s, "lowerRoman", 2)

names_inline = ", ".join(f"{n} ({r})" for n, r in TEAM[:-1]) + f", {TEAM[-1][0]} ({TEAM[-1][1]})"

para("DECLARATION", bold=True, align="center", size=16, after=14)
body(
    f"This is to certify that the Minor Project Report titled “{TITLE}” for the Minor Project (AIDS451) "
    f"is submitted by {names_inline} of 7th Semester, Section B, in partial fulfillment of the requirement for the "
    "award of the degree of B.Tech. in Artificial Intelligence and Data Science, Vivekananda Institute of "
    "Professional Studies – Technical Campus (VIPS-TC), Guru Gobind Singh Indraprastha University, Dwarka, "
    "Delhi. It comprises our original work. Due affirmation and proper citations have been made within the report "
    "for utilizing all referenced work."
)
para("Date: ______________________", before=14)
signature_block()

page_break()
para("CERTIFICATE BY SUPERVISOR", bold=True, align="center", size=16, after=14)
body(
    f"This is to certify that the Minor Project Report titled “{TITLE}” for the Minor Project (AIDS451) "
    f"is submitted by {names_inline} of 7th Semester, Section B, in partial fulfillment of the requirement for the "
    "award of the degree of B.Tech. in Artificial Intelligence and Data Science, Vivekananda Institute of "
    "Professional Studies – Technical Campus (VIPS-TC), Guru Gobind Singh Indraprastha University, Dwarka, "
    "Delhi. It is a record of the candidates’ own work carried out by them under my supervision. The matter "
    "embodied in this Report is original and has not been submitted for the award of any other degree."
)
para("Date: ______________________", before=14)
para("(Signature)", before=30, after=0)
para(SUPERVISOR, after=0)
para("Supervisor, Department of Artificial Intelligence and Data Science", after=0)
para("VSET, VIPS-TC", after=24)
para("___________________________", after=0)
para("Signature of HOD", after=0)

page_break()
para("ACKNOWLEDGMENT", bold=True, align="center", size=16, after=14)
body(
    "We would like to express our heartfelt gratitude to all those who have contributed to the successful "
    f"completion of our minor project report titled “{TITLE}.” First and foremost, we extend our deepest "
    f"appreciation to our project supervisor, {SUPERVISOR}, for the constant guidance, valuable insights, "
    "constructive feedback, and unwavering support throughout the design, implementation, and evaluation of Sawaal."
)
body(
    "We are also indebted to the Head of Department, Programme Coordinator, and the esteemed faculty members of "
    "Vivekananda School of Engineering and Technology (VSET), VIPS-TC, GGSIPU, Dwarka, Delhi, whose academic "
    "mentorship and technical resources were instrumental in enriching our learning experience. Finally, we are grateful to our fellow students and families for their "
    "continuous encouragement and support throughout the 7th Semester."
)
for name, roll in TEAM:
    para("___________________________", before=14, after=0)
    para(f"{name} ({roll})", after=0)

page_break()
para("Table of Contents", bold=True, align="center", size=16, after=14)
toc = doc.add_paragraph()
field(toc, 'TOC \\o "1-2" \\h \\z \\u', "Right-click here and choose Update Field to build the table of contents.")

page_break()
para("List of Figures", bold=True, align="center", size=16, after=14)
lof = doc.add_paragraph()
field(lof, 'TOC \\h \\z \\t "Figure Caption,1"', "Right-click here and choose Update Field.")

page_break()
para("List of Tables", bold=True, align="center", size=16, after=14)
lot = doc.add_paragraph()
field(lot, 'TOC \\h \\z \\t "Table Caption,1"', "Right-click here and choose Update Field.")

page_break()
para("Abstract", bold=True, align="center", size=16, after=14)
body(
    "Most of the world’s useful data sits in relational databases, but getting an answer out of one requires "
    "Structured Query Language (SQL) and knowledge of the table layout, which many people who need the answers never "
    "learn. Sawaal is a web application that lets a user type a question in English or Hinglish, or speak it, and "
    "returns the answer as a plain-language sentence, a table and a chart, together with the exact SQL that produced "
    "it. A large language model writes the query; a safety layer guarantees that only a single read-only query can "
    "ever run; the database executes it; and if the database reports an error, the error is sent back to the model "
    "so that it can repair its own query."
)
body(
    "Sawaal is built with a FastAPI backend, a React and TypeScript frontend, SQLAlchemy for database access and "
    "the sqlglot parser for query validation. It works with the built-in sample databases, with uploaded CSV and "
    "SQLite files, and with live PostgreSQL and MySQL databases. Beyond translating questions, it routes a question "
    "to the database that holds the data, answers questions about uploaded PDF documents with page citations, "
    "proposes starter dashboards, and learns from use: confirmed question and SQL pairs and plain-language business "
    "rules are stored and recalled for later questions. It also adds three user roles with restricted tables that are enforced on the parsed SQL, an audit log of every "
    "question and denied request, and streamed progress while an answer is being produced."
)
body(
    "Evaluation is built into the project: a benchmark of 29 questions on four databases (each with a known-correct "
    "query) measures execution accuracy in the manner of the Spider benchmark, and 231 automated tests cover the "
    "safety layer, access control and the API. In this report, the benchmark harness is verified end to end and all "
    "29 reference queries execute and match; the accuracy of a live model on the benchmark is reported separately as "
    "a run that requires an API key. An offline Demo mode allows the whole system to be presented without a key."
)
para("Keywords: Text-to-SQL, natural language interface to databases, large language models, read-only guard, "
     "role-based access control, retrieval, FastAPI, React.", italic=True, align="justify")

# ================================================================ BODY
s = new_section()
footer_page_number(s, "decimal", 1)

# ------------------------------------------------------------ Chapter 1
h1("Chapter 1: Introduction")
h2("1.1 Background and Motivation")
body(
    "Schools, hospitals, shops, companies and government offices keep their records in relational databases. A "
    "relational database stores data in tables whose rows are linked by keys, and it is queried with SQL. Getting a "
    "useful answer out of it, such as “which department spends the most on salaries”, needs a query that "
    "joins several tables, groups the rows and sorts the result, and it needs the exact names of the tables and "
    "columns involved. The people who hold the business questions, such as managers, teachers and officials, "
    "usually do not have this skill, while the people who do have it, such as analysts and database administrators, "
    "spend much of their time on repetitive requests."
)
body(
    "Dashboards help only partly. A dashboard answers the questions its designer anticipated; the first follow-up "
    "question that crosses a table boundary sends the request back to the engineering queue. Recent large language "
    "models (LLMs) are good at turning a sentence into code, including SQL, and this makes a natural language "
    "interface to databases (NLIDB) practical for the first time. Our motivation is to build such an interface that "
    "an ordinary user can trust and that a developer can inspect."
)
h2("1.2 Limitations of Naive LLM-to-SQL Wrappers")
body(
    "A simple wrapper that sends the user’s sentence to an LLM and runs whatever SQL comes back has four "
    "well-known weaknesses. First, without the real schema the model invents table and column names. Second, there "
    "is no feedback: when the database rejects the query, the user sees a raw error. Third, running model-written "
    "SQL directly is a security risk, because a mistaken or prompt-injected statement such as DROP or DELETE would "
    "change real data, and a query could expose personal columns or tables the user should not see. Fourth, the "
    "user cannot tell a right answer from a plausible wrong one, because neither the query nor the accuracy of the "
    "system is shown."
)
h2("1.3 Overview of Sawaal")
body(
    "Sawaal (Hindi for “question”) addresses these weaknesses with a pipeline in which the model is only "
    "one component. The schema, with sample values and key relationships, is read from the live database and given "
    "to the model. The model returns one SQL query. That query is parsed and must be a single read-only SELECT; it "
    "is also checked against the tables the signed-in user may read. It is then executed on a read-only connection "
    "with a time limit and a row limit. If the database returns an error, the error is fed back and the model "
    "writes a corrected query, up to three times. Personal columns such as email and phone are masked in the "
    "result. A second short model call writes a summary and suggests follow-up questions. The page always shows the "
    "SQL, so the answer can be checked."
)
body(
    "The first version of the project provided this core pipeline. The version described in this report adds "
    "document question answering over PDFs, suggested dashboards, connections to PostgreSQL and MySQL, a training "
    "memory, three user roles with restricted tables, an audit log, streamed progress, and an offline Demo mode.."
)
h2("1.4 Key Contributions and Report Organization")
bullet(" a working full-stack system (React, FastAPI, SQLAlchemy) that answers questions as text, table, chart and SQL.",
       "End-to-end NLIDB:")
bullet(" a parsed read-only guard plus a read-only connection, timeouts and row limits, so that two independent "
       "layers would have to fail before data could change.", "Defence in depth:")
bullet(" confirmed examples and business rules are stored per database and recalled by keyword ranking (BM25) "
       "to improve later answers without retraining a model.", "Training memory:")
bullet(" viewer, analyst and admin roles; restricted tables enforced on the parsed SQL, including through common "
       "table expressions; an audit log of questions and denials.", "Roles, restricted tables and audit:")
bullet(" PDF question answering with page citations, database routing, dashboard suggestions, live PostgreSQL and "
       "MySQL connections, and Server-Sent Events streaming of progress.", "Practical features:")
bullet(" a 29-question benchmark with known-correct SQL and an execution-accuracy harness, and 231 automated tests.",
       "Measurement:")
body(
    "The remainder of the report is organized as follows. Chapter 2 surveys related work. Chapter 3 states the "
    "problem and the objectives. Chapter 4 gives the requirements and the system design with diagrams. Chapter 5 "
    "describes the methodology and each module. Chapter 6 presents the results of the verification and testing. "
    "Chapter 7 concludes and Chapter 8 lists future work."
)

# ------------------------------------------------------------ Chapter 2
page_break()
h1("Chapter 2: Related Work")
h2("2.1 Early Natural Language Interfaces to Databases")
body(
    "Natural language interfaces to databases date back to rule-based systems such as LUNAR and LADDER, which mapped "
    "English questions to queries with hand-written grammars and domain dictionaries. They were accurate in a narrow "
    "domain but brittle: a paraphrase could break a rule, and moving to a new schema meant weeks of manual work. "
    "Statistical and neural methods replaced the grammars. Seq2SQL [1] used reinforcement learning to generate "
    "queries for single tables, and later models handled joins and nested queries but generalised poorly to "
    "databases they had not seen."
)
h2("2.2 Benchmarks: WikiSQL, Spider, BIRD and Spider 2.0")
body(
    "Progress has been driven by benchmarks. WikiSQL [1] provided tens of thousands of question and SQL pairs but "
    "only over single tables. Spider [2] introduced 200 multi-table databases across many domains and made the model "
    "work on schemas it had not seen; it popularised two metrics, exact set match and execution accuracy (EX). "
    "Execution accuracy counts a prediction as correct when it returns the same result as the gold query, however "
    "the query is written, and is the metric used in this project. BIRD [4] added large, noisy databases and "
    "external knowledge, and Spider 2.0 [5] moved towards enterprise workflows with many steps."
)
h2("2.3 LLM Prompting, Tool Use and Retrieval")
body(
    "With large language models, strong results came from prompting rather than from training a specialised "
    "parser. DIN-SQL [6] showed that decomposing the task into schema linking, generation and self-correction "
    "improves accuracy. ReAct [7] showed that letting a model act, observe and revise reduces hallucination, and "
    "the idea of feeding a database error back to the model is a direct use of it. Retrieval-augmented generation "
    "[8] supplies a model with relevant passages at question time; Sawaal uses the same idea twice, once to recall "
    "taught examples and rules and once to answer from PDF documents. Retrieval uses BM25 [9], a classic keyword "
    "ranking function."
)
h2("2.4 Comparative Summary and Gap")
body(
    "Table 2.1 compares the related systems with Sawaal. Benchmarks measure models, not applications; research methods and toolkits "
    "give building blocks but leave out the interface, access control by user and the safety checks that an "
    "organisation needs before letting non-technical people near a database. Sawaal aims to fill that gap with a "
    "complete, inspectable and measurable application."
)
table(
    ["System", "Kind", "Main contribution", "Limitation for our purpose"],
    [
        ["WikiSQL (2017)", "Dataset", "Large single-table question and SQL set", "No joins or nested queries"],
        ["Spider (2018)", "Benchmark", "Cross-domain, multi-table, unseen schemas; EX metric", "Measures a model, not a usable system"],
        ["BIRD (2023)", "Benchmark", "Large, noisy databases; external knowledge", "No interface, safety or access control"],
        ["DIN-SQL (2023)", "Method", "Decomposed prompting with self-correction", "Research code, no application"],
        ["Sawaal (ours)", "Application", "Guarded pipeline, training, roles, audit, documents, dashboards, benchmark", "Accuracy depends on the model used"],
    ],
    widths=[1.1, 0.9, 2.4, 1.9],
)
caption("Table", "Table 2.1: Comparative Analysis of Related Text-to-SQL Work and Sawaal")

# ------------------------------------------------------------ Chapter 3
page_break()
h1("Chapter 3: Problem Statement and Objectives")
h2("3.1 Problem Statement")
body(
    "Non-technical users need quick and correct answers from relational databases without learning SQL, and the "
    "organisation that owns the data needs to be sure that this convenience does not endanger the data. Using an "
    "LLM directly creates five engineering problems:"
)
bullet(" the model invents tables and columns, or misspells values such as a city or a status, unless it is given "
       "the real schema and sample values.", "Hallucinated names:")
bullet(" a wrong query is returned as a raw error, and a wrong but valid query is returned as a confident "
       "answer.", "No recovery and no verification:")
bullet(" model-written SQL may modify data, run for too long, return too many rows or expose personal data.",
       "Unsafe execution:")
bullet(" all users see all tables, and nobody can later tell who asked what.", "No access control or accountability:")
bullet(" the same mistakes repeat because the system does not learn the organisation’s own definitions, "
       "for example what counts as an “active” customer.", "No memory of business knowledge:")
h2("3.2 Objectives")
bullet(" convert English and Hinglish questions into correct SQL for any relational database, using the live "
       "schema.", "Objective 1, accurate translation:")
bullet(" guarantee read-only access with two independent layers, a query timeout and a row limit.",
       "Objective 2, safe execution:")
bullet(" repair failed queries automatically using the database error.", "Objective 3, self-repair:")
bullet(" present each answer as a summary, a table, a chart and the SQL, with suggested follow-up questions.",
       "Objective 4, understandable answers:")
bullet(" let the system learn examples and business rules, and use them on later questions.",
       "Objective 5, learning from use:")
bullet(" provide viewer, analyst and admin roles, restricted tables, masking of personal data, rate limiting and "
       "an audit log.", "Objective 6, control and accountability:")
bullet(" measure accuracy with a repeatable benchmark in the style of Spider’s execution accuracy.",
       "Objective 7, measurement:")
h2("3.3 Scope")
body(
    "The system answers questions about structured data in SQLite, CSV, PostgreSQL and MySQL, and about text in PDF "
    "files. It never writes to a database. It is designed for a small organisation or a classroom and runs on a "
    "single machine; the model itself is a cloud service (Claude or Groq). Training a new language model is outside "
    "the scope of the project."
)

# ------------------------------------------------------------ Chapter 4
page_break()
h1("Chapter 4: Project Analysis and Design")
h2("4.1: Hardware and Software Requirement Specifications (H/W and S/W requirements)")
body(
    "Sawaal is a lightweight software system. The heavy model computation is done by a cloud API, so no GPU is "
    "needed; the backend, the databases and the web interface run locally on an ordinary laptop. Table 4.1 lists the "
    "environment used for development and testing."
)
table(
    ["Component", "Specification"],
    [
        ["Processor", "Any 64-bit CPU (development machine: Apple silicon Mac)"],
        ["Memory", "4 GB minimum, 8 GB recommended"],
        ["Storage", "About 500 MB for the code, packages and sample data"],
        ["Network", "Internet access for the AI provider (not needed in Demo mode)"],
        ["Operating system", "macOS, Windows or Linux"],
        ["Backend", "Python 3.11 or later (tested on 3.14), FastAPI 0.162, Uvicorn, SQLAlchemy 2.1, Pydantic 2.14"],
        ["SQL safety", "sqlglot 30.31 (parser and validator)"],
        ["AI providers", "Anthropic Claude (anthropic 2.8) or Groq (groq 1.7, free tier); offline Demo AI"],
        ["Data access", "SQLite (built in), PostgreSQL (psycopg 3.3), MySQL (PyMySQL 1.2), pypdf 7.1 for PDFs"],
        ["Security", "scrypt password hashing, Fernet encryption (cryptography 50.0)"],
        ["Frontend", "Node.js 20 or later, React 19, TypeScript, Vite 8, CodeMirror, Recharts"],
        ["Testing", "pytest, ruff (lint), TypeScript compiler, Vite production build"],
    ],
    widths=[1.5, 4.8],
)
caption("Table", "Table 4.1: Hardware and Software Requirement Specifications")
body("Table 4.2 lists the functional and non-functional requirements and how each one is verified.")
table(
    ["ID", "Type", "Requirement"],
    [
        ["FR-1", "Functional", "Accept a question in English, Hinglish or speech and return a summary, table, chart and the SQL."],
        ["FR-2", "Functional", "Read the live schema, keys and sample values and use them in the prompt."],
        ["FR-3", "Functional", "Run only a single read-only query; refuse anything else with a clear reason."],
        ["FR-4", "Functional", "Return a database error to the model and retry up to three times."],
        ["FR-5", "Functional", "Route a question to the database that holds the data when the chosen one does not."],
        ["FR-6", "Functional", "Store confirmed examples and business rules and recall them for later questions."],
        ["FR-7", "Functional", "Answer questions about uploaded PDFs with page citations."],
        ["FR-8", "Functional", "Sign users in, apply their role, hide and block restricted tables, and log every question and denial."],
        ["FR-9", "Functional", "Show progress while an answer is being produced (streaming)."],
        ["NFR-1", "Security", "Two independent layers must prevent data modification; connection passwords are stored encrypted."],
        ["NFR-2", "Performance", "Queries time out after 15 seconds and return at most 1,000 rows."],
        ["NFR-3", "Privacy", "Columns that look like personal data are masked in results."],
        ["NFR-4", "Reliability", "The whole test suite runs offline using a scripted stand-in for the model."],
        ["NFR-5", "Usability", "Light and dark themes, keyboard command palette, works on a phone-width screen."],
    ],
    widths=[0.7, 1.1, 4.5],
)
caption("Table", "Table 4.2: Functional and Non-Functional System Requirements")

h2("4.2: Use Case Diagrams, Flow Chart/ Activity Diagram")
body(
    "The design is described by four diagrams: the system architecture (Figure 4.1), the processing workflow "
    "(Figure 4.2), the use case diagram (Figure 4.3) and a sequence diagram of one question (Figure 4.4)."
)
body(
    "Figure 4.1 shows the architecture. The browser talks to a FastAPI backend, which holds the sign-in, role and "
    "rate-limit checks and streams progress as Server-Sent Events. For each question the backend gathers the schema "
    "and the recalled training, sends them to the AI model, receives a query, checks it with the guard, and passes "
    "it to the executor, which runs it on the selected database, applies masking and returns the rows. Users, "
    "sessions, the audit log, history, training memory and document passages are kept in small SQLite files beside "
    "the application."
)
figure("fig_4_1_architecture.png", "Figure 4.1: Sawaal System Architecture", 5.9)
body(
    "Figure 4.2 shows the processing steps for one question. The two highlighted checks, the read-only guard and the "
    "restricted-table check, run on the parsed query before anything touches the database; a refusal is written to "
    "the audit log. A database error does not end the request: it is sent back to the model for a repaired query, "
    "up to three times."
)
figure("fig_4_2_workflow.png", "Figure 4.2: Sawaal Question Processing and Repair Workflow", 4.9)
body(
    "Figure 4.3 shows who can do what. A viewer can ask questions and see answers, but restricted tables are hidden "
    "and blocked. An analyst can also teach the system, upload files and PDFs and pin dashboard charts. An admin can "
    "additionally connect or delete databases, manage users and read the audit log. The AI model is an external "
    "actor that only ever receives text and returns SQL."
)
figure("fig_4_3_usecase.png", "Figure 4.3: Sawaal UML Use Case Diagram", 5.9)
body(
    "Figure 4.4 follows one question through the system. The backend is the only component that talks to both the "
    "model and the database; the model never holds a database connection, and every query it writes must pass the "
    "guard first."
)
figure("fig_4_4_sequence.png", "Figure 4.4: Sawaal Runtime Sequence Diagram", 5.9)

h2("4.3: Connection Diagram")
body(
    "Not applicable. Sawaal is a purely software-based system; no electronic circuits, microcontrollers or "
    "communication modules are involved."
)
h2("4.4: Description of Hardware Components used")
body(
    "Not applicable. The project uses only a general-purpose computer (a laptop) with a web browser and, for the "
    "voice feature, the microphone that the browser already provides."
)

# ------------------------------------------------------------ Chapter 5
page_break()
h1("Chapter 5: Proposed Work and Methodology Adopted")
h2("5.1 Overall Approach")
body(
    "The central design idea is that the language model is trusted to be helpful but never trusted to be safe. "
    "Everything that must always be true, such as read-only access, restricted tables, row limits and masking, is "
    "enforced by ordinary code around the model, not by asking the model to behave. The model contributes only what "
    "it is good at: reading the schema and the question and writing a query."
)
h2("5.2 Modules")
modules = [
    ("Schema reader.", "Reads tables, columns, types, keys, row counts, sample rows and the values of short "
     "categorical columns through SQLAlchemy, and formats them as compact CREATE TABLE statements for the prompt, so "
     "that the model uses exact names and spellings."),
    ("SQL generator.", "Asks the model for a structured answer (answerable, SQL, explanation). Follow-up questions "
     "receive the previous questions and queries as context. Anthropic Claude and Groq are supported."),
    ("SQL guard.", "Parses the query with sqlglot and accepts only one SELECT-type statement. It rejects INSERT, "
     "UPDATE, DELETE, DROP, ATTACH, PRAGMA, SELECT INTO, multiple statements and dangerous functions such as "
     "pg_sleep and load_extension."),
    ("Executor.", "Runs the query on a read-only connection with a 15-second timeout and a 1,000-row cap."),
    ("Self-repair loop.", "On a database error, sends the failed query and the error back to the model and runs "
     "the corrected query, at most three times."),
    ("Database router.", "When the chosen database does not hold the data, the model is shown a short catalogue of "
     "all databases and picks the right one."),
    ("Insight engine.", "Writes a plain-language summary and three follow-up questions from the first rows of the "
     "result. If this step fails, the table is still shown."),
    ("Explainer.", "Explains any query step by step for people learning SQL."),
    ("Privacy layer.", "Masks columns whose names look like personal data (email, phone, Aadhaar, card numbers)."),
    ("Rate limiter.", "Limits model calls per client per minute."),
    ("Data profiler and ER diagram.", "Per-column empty counts, distinct counts and ranges without using the "
     "model, and a relationship diagram drawn from foreign keys."),
    ("Importer and connection manager.", "CSV files become tables and SQLite files are attached. PostgreSQL and "
     "MySQL URLs are tested, then stored encrypted with Fernet; only those two drivers are accepted, because a "
     "SQLite URL would let a caller read any file on the server."),
    ("Document search (RAG).", "PDFs are split into passages of about 900 characters tagged with their page and "
     "ranked with BM25. The best six passages go to the model, which must answer only from them and cite them by "
     "number. If a database is selected, its answer is added as one more source."),
    ("Dashboard suggester.", "The model proposes charts from the schema; each query passes the same guard and is "
     "dropped if it fails or returns nothing. Without a model, rules over column types build the charts."),
    ("Training memory.", "Stores confirmed question and SQL pairs and plain-language rules for each database. For "
     "each new question the three most similar examples and up to eight rules are ranked by BM25 and added to the "
     "prompt. Taught SQL must pass the guard before it is saved."),
    ("Roles, restricted tables and audit.", "Described in Section 5.3."),
    ("Streaming.", "The endpoint /api/generate/stream sends Server-Sent Events (status, sql, repair, done) so that "
     "the page shows each step as it happens."),
    ("Demo mode.", "An offline stand-in for the model that answers the benchmark questions with their reference "
     "SQL. It exists so that the system can be presented without an API key; the interface labels it “Demo AI”."),
]
for i, (lead, text) in enumerate(modules, start=1):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.left_indent = Inches(0.3)
    p.paragraph_format.first_line_indent = Inches(-0.3)
    p.paragraph_format.space_after = Pt(4)
    p.add_run(f"{i}. ")
    p.add_run(lead + " ").bold = True
    p.add_run(text)

h2("5.3 Roles, Restricted Tables and Audit")
body(
    "Sign-in is optional so that a single user can run the tool locally; when it is switched on, passwords are "
    "hashed with scrypt and a session is kept in an HttpOnly cookie. Each request passes a middleware that maps the "
    "method and path to a minimum role (Table 5.1). Tables named in the RESTRICTED_TABLES setting are removed from "
    "the schema shown to a viewer and from the prompt, and, independently, any query that reads one of them is "
    "refused. The second check parses the SQL and collects the real table names, ignoring names defined by WITH "
    "clauses, so that a viewer cannot reach a restricted table through a subquery or a common table expression. "
    "Every question, upload, connection, deletion, login and denied request is recorded with the user, role, "
    "status and time."
)
table(
    ["Capability", "Viewer", "Analyst", "Admin"],
    [
        ["Ask questions, see answers and history", "Yes", "Yes", "Yes"],
        ["Restricted tables", "Hidden and blocked", "Allowed", "Allowed"],
        ["Teach examples and rules; documents; uploads; pin charts", "No", "Yes", "Yes"],
        ["Connect or delete databases", "No", "No", "Yes"],
        ["Manage users and read the audit log", "No", "No", "Yes"],
    ],
    widths=[3.2, 1.1, 1.0, 1.0],
)
caption("Table", "Table 5.1: Role Permissions in Sawaal")

h2("5.4 Backend Interface")
body("Table 5.2 lists the main REST endpoints of the FastAPI backend.")
table(
    ["Endpoint", "Purpose"],
    [
        ["POST /api/generate", "Question to SQL, result, summary and follow-ups in one response"],
        ["POST /api/generate/stream", "Same, as Server-Sent Events with progress steps"],
        ["POST /api/execute", "Run SQL typed by the user (still guarded, read-only)"],
        ["POST /api/explain", "Explain a query step by step"],
        ["GET /api/databases, /schema, /profile, /examples", "List databases; schema, data profile and example questions"],
        ["POST /api/databases/upload, /connect; DELETE /api/databases/{id}", "Add CSV or SQLite files; connect PostgreSQL or MySQL; remove a database"],
        ["POST /api/databases/{id}/auto-dashboard", "Suggested charts for a database"],
        ["GET, POST, DELETE /api/documents; POST /api/documents/ask", "Manage PDFs and ask questions about them"],
        ["GET /api/memory; POST /api/memory/examples, /notes; DELETE /api/memory/{id}", "Training memory"],
        ["POST /api/auth/login, /logout; GET /api/auth/me", "Sign in and out; current user"],
        ["GET, POST, DELETE /api/users; GET /api/audit", "User management and audit log (admin)"],
        ["GET /api/history, /api/stats", "Past questions and usage statistics"],
    ],
    widths=[3.3, 3.0],
)
caption("Table", "Table 5.2: FastAPI Backend REST Endpoint Summary")

h2("5.5 Data Used for Development and Evaluation")
body(
    "Four sample databases are generated by the application so that it can be demonstrated without any outside "
    "data. E-commerce has 7 tables with 300 customers, 2,000 orders and 3,675 order lines. School has 7 tables with "
    "240 students and 5,760 marks. Company has 7 tables with 321 employees and 5,806 payroll rows. Government has "
    "6 tables with 4,500 grievances and 712 hospitals. Figure 5.1 shows the relationships among the E-commerce "
    "tables as an example."
)
figure("fig_5_1_er.png", "Figure 5.1: E-commerce Sample Database Schema (ER Diagram)", 5.6)

h2("5.6 Evaluation Methodology")
body(
    "Accuracy is measured with execution accuracy, as in Spider [2]. For each benchmark question, the system’s "
    "query and the reference query are both executed on the same database, and the question counts as correct when "
    "the result sets match. The comparison ignores row order and column order, tolerates small rounding "
    "differences and allows extra columns, because different correct queries may return different columns. The "
    "benchmark (backend/eval/golden.json) holds 29 questions, graded easy, medium and hard, on four databases. "
    "Every reference query was written by hand and is executed by the harness itself, so a mistake in a reference "
    "query would show up as a failure."
)
body(
    "Two kinds of measurement are kept apart in this report. The first, in Section 6.2, verifies that the harness, "
    "the databases and the reference queries are correct by running the whole benchmark through the real evaluation "
    "code with the scripted Demo AI. Because the Demo AI returns the reference query, this measures the harness, not "
    "a language model. The second, in Section 6.4, is the accuracy of a live model (Claude or Groq), which is "
    "obtained by running the same harness with an API key."
)

# ------------------------------------------------------------ Chapter 6
page_break()
h1("Chapter 6: Results and Discussion")
h2("6.1 Evaluation Environment")
table(
    ["Parameter", "Setting"],
    [
        ["Benchmark", "29 questions, 4 databases (E-commerce 9, Company 7, Government 7, School 6)"],
        ["Difficulty mix", "Easy 9, Medium 12, Hard 8"],
        ["Metric", "Execution accuracy (result-set match), as in Spider"],
        ["Harness", "python -m app.evaluate (backend/app/evaluate.py)"],
        ["Verification run", "Demo AI (scripted), real databases, real executor and guard"],
        ["Test suite", "pytest, 231 test cases in 18 files, run offline"],
        ["Platform", "macOS, Python 3.14, Node.js 22"],
    ],
    widths=[1.6, 4.7],
)
caption("Table", "Table 6.1: Evaluation Environment and Configuration")
figure("fig_6_1_benchmark.png", "Figure 6.1: Composition of the 29-Question Benchmark by Database and Difficulty", 5.4)

h2("6.2 Benchmark Harness Verification")
body(
    "All 29 benchmark questions were run through the real evaluation code. Each reference query passed the SQL "
    "guard, executed on its database, and was compared with the expected result. All 29 matched, giving a harness "
    "execution accuracy of 100% (29 of 29). The mean time to execute one query was about 2 milliseconds and the slowest "
    "was about 20 milliseconds, so database execution is a negligible part of the time a user waits; in practice the wait "
    "is dominated by the model call. This result shows that the benchmark is sound and the executor and comparison "
    "work. It is not an estimate of the accuracy of a language model, which is the subject of Section 6.4."
)
table(
    ["Database", "Questions", "Executed and matched", "Easy / Medium / Hard"],
    [
        ["E-commerce", "9", "9 of 9", "3 / 3 / 3"],
        ["Company", "7", "7 of 7", "2 / 3 / 2"],
        ["Government", "7", "7 of 7", "2 / 3 / 2"],
        ["School", "6", "6 of 6", "2 / 3 / 1"],
        ["Total", "29", "29 of 29 (100%)", "9 / 12 / 8"],
    ],
    widths=[1.5, 1.1, 2.0, 1.7],
)
caption("Table", "Table 6.2: Benchmark Harness Verification (Scripted Demo AI)")

h2("6.3 Safety and Access-Control Testing")
body(
    "The safety layer is tested with 231 automated test cases that run without a network connection, using a "
    "scripted stand-in for the model. The guard has 10 queries that must be accepted and 22 that must be refused, "
    "covering data-changing statements, multiple statements, SELECT INTO, ATTACH, PRAGMA, dangerous functions and "
    "unparseable text. The access-control tests check that a viewer is refused a restricted table when it is named "
    "directly and when it is hidden inside a WITH clause, that an analyst cannot manage users, that the audit log "
    "records denials, that repeated wrong passwords are limited, and that the streaming endpoint delivers its "
    "events. Further tests cover schema reading, CSV import, routing, repair, insights, explanations, masking, "
    "profiling, the training memory, documents, dashboard suggestions and connections. All 231 pass, and the "
    "linter (ruff), the TypeScript type check and the production build of the frontend complete without errors."
)
figure("fig_6_2_tests.png", "Figure 6.2: Automated Test Functions by Area", 5.4)
table(
    ["Threat", "Defence", "How it is checked"],
    [
        ["Model writes a destructive query", "Parsed allow-list, then a read-only connection", "22 refused-query test cases"],
        ["Runaway or huge query", "15-second timeout, 1,000-row cap", "Database tests"],
        ["Viewer reads a restricted table", "Hidden from prompt and schema; refused on the parsed SQL", "Direct and WITH-clause bypass tests"],
        ["Leak of personal data", "Name-based column masking", "Masking tests"],
        ["Stolen connection passwords", "Fernet encryption; only PostgreSQL and MySQL URLs", "Connection tests"],
        ["Password guessing", "scrypt hashing; login rate limit", "Auth tests"],
        ["Unattributed actions", "Audit log of questions, changes and denials", "Audit tests"],
    ],
    widths=[1.9, 2.4, 2.0],
)
caption("Table", "Table 6.3: Threats, Defences and How They Are Verified")

h2("6.4 Live Model Accuracy")
body(
    "The accuracy of a live model is measured by running the same 29 questions against Claude or Groq. The command "
    "is shown below. At the time of writing this report no API key was configured on the development machine, so "
    "this run has not yet been made and its figures are not given here; Table 6.4 is left for the team to complete "
    "from the report that the command saves (data/eval). We have chosen to leave these cells blank, instead of "
    "estimating them, because the value of an execution-accuracy figure comes from its being measured."
)
para("cd backend && python -m app.evaluate --delay 3", italic=True, align="center")
table(
    ["Model", "Easy", "Medium", "Hard", "Overall", "Right on first try", "Average time"],
    [["__", "__", "__", "__", "__", "__", "__"], ["__", "__", "__", "__", "__", "__", "__"]],
    widths=[1.3, 0.7, 0.8, 0.7, 0.8, 1.2, 0.9],
    highlight_blank=True,
)
caption("Table", "Table 6.4: Live Model Execution Accuracy on the Benchmark (to be completed)")

h2("6.5 Discussion and Limitations")
bullet(" a model can still write a plausible query that answers a different question. The system reduces this by "
       "showing the SQL, by learning confirmed examples and rules, and by measuring accuracy, but it cannot remove it.",
       "Accuracy depends on the model:")
bullet(" only the first rows of a result are sent to the model for the written summary, so the summary of a very "
       "large result is based on a sample.", "Summaries use a sample:")
bullet(" document retrieval uses BM25, so a question that uses different words from the document can miss it, and "
       "scanned PDFs need OCR first.", "Keyword retrieval:")
bullet(" masking is based on column names, so a personal column with an unusual name would not be hidden.",
       "Name-based masking:")
bullet(" the rate limiter and sessions are kept in the memory of one process, which suits a single server but not "
       "a cluster.", "Single-process design:")
bullet(" the benchmark has 29 questions on four generated databases; it shows relative progress but is small "
       "compared with Spider or BIRD.", "Small benchmark:")

# ------------------------------------------------------------ Chapter 7
page_break()
h1("Chapter 7: Conclusion")
body(
    "Sawaal shows that a natural language interface to databases can be built so that a non-technical user gets a "
    "readable answer while the organisation keeps control. The model is treated as an assistant whose output is "
    "always checked: every query is parsed, restricted to one read-only statement, checked against the tables the "
    "user may read, executed with limits and, when it fails, repaired from the database’s own error message. "
    "The SQL is always visible, so the answer can be verified."
)
body(
    "We added a training memory, user roles with restricted tables, an audit log and "
    "streaming, which turned a question-answering tool into something closer to a system a small team could "
    "actually deploy. The project also treats measurement as part of the product: a benchmark with reference "
    "queries and an execution-accuracy harness, verified here on all 29 questions, and 231 automated tests that run "
    "offline. The remaining step, the accuracy of a live model on the benchmark, is a single command once an API "
    "key is available."
)
body(
    "Working on the project taught us how to combine a web backend, a typed frontend, a SQL parser and an external "
    "AI service into one application, and how much of the work in an AI application lies in the checks, "
    "limits and tests around the model."
)

# ------------------------------------------------------------ Chapter 8
page_break()
h1("Chapter 8: Future Scope of Work")
for lead, text in [
    ("Measured accuracy study.", " run the benchmark on several models, report accuracy with and without training "
     "memory, and enlarge the benchmark with more questions, ambiguous questions and Hinglish phrasing."),
    ("Embedding-based retrieval.", " replace or combine BM25 with vector search for documents and for recalling "
     "examples, and add OCR for scanned files."),
    ("Schema pruning for wide databases.", " for databases with dozens of tables, select the relevant tables "
     "before building the prompt to keep it short and accurate."),
    ("Column-level permissions.", " extend restricted tables to individual columns and to row filters per user."),
    ("Production hardening.", " shared session and rate-limit storage, single sign-on, HTTPS deployment and "
     "per-user history."),
    ("More sources and outputs.", " Excel upload and export, scheduled dashboards, result caching and additional "
     "database engines."),
    ("Local models.", " support a locally hosted or fine-tuned model so that data never leaves the organisation."),
]:
    bullet(text, lead)

# ------------------------------------------------------------ References
page_break()
para("REFERENCES", bold=True, align="center", size=16, after=14)
refs = [
    "V. Zhong, C. Xiong, and R. Socher, “Seq2SQL: Generating structured queries from natural language using "
    "reinforcement learning,” arXiv preprint arXiv:1709.00103, 2017.",
    "T. Yu et al., “Spider: A large-scale human-labeled dataset for complex and cross-domain semantic parsing "
    "and text-to-SQL task,” in Proc. Conf. Empirical Methods in Natural Language Processing (EMNLP), Brussels, "
    "Belgium, 2018, pp. 3911–3921.",
    "B. Wang, R. Shin, X. Liu, O. Polozov, and M. Richardson, “RAT-SQL: Relation-aware schema encoding and "
    "linking for text-to-SQL parsers,” in Proc. 58th Annual Meeting of the Association for Computational "
    "Linguistics (ACL), 2020, pp. 7567–7578.",
    "J. Li et al., “Can LLM already serve as a database interface? A big bench for large-scale database "
    "grounded text-to-SQLs,” in Advances in Neural Information Processing Systems (NeurIPS), 2023.",
    "F. Lei et al., “Spider 2.0: Evaluating language models on real-world enterprise text-to-SQL workflows,” "
    "arXiv preprint arXiv:2411.07763, 2024.",
    "M. Pourreza and D. Rafiei, “DIN-SQL: Decomposed in-context learning of text-to-SQL with self-correction,” "
    "in Advances in Neural Information Processing Systems (NeurIPS), 2023.",
    "S. Yao et al., “ReAct: Synergizing reasoning and acting in language models,” in Proc. International "
    "Conference on Learning Representations (ICLR), 2023.",
    "P. Lewis et al., “Retrieval-augmented generation for knowledge-intensive NLP tasks,” in Advances in "
    "Neural Information Processing Systems (NeurIPS), 2020.",
    "S. Robertson and H. Zaragoza, “The probabilistic relevance framework: BM25 and beyond,” Foundations "
    "and Trends in Information Retrieval, vol. 3, no. 4, pp. 333–389, 2009.",
    "S. Ramírez, “FastAPI,” https://fastapi.tiangolo.com, accessed 2026.",
    "tobymao, “sqlglot: Python SQL parser and transpiler,” https://github.com/tobymao/sqlglot, accessed 2026.",
]
for i, r in enumerate(refs, start=1):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.left_indent = Inches(0.4)
    p.paragraph_format.first_line_indent = Inches(-0.4)
    p.add_run(f"[{i}] {r}")

# Ask Word to refresh the table of contents and lists when the file is opened.
settings = doc.settings.element
upd = OxmlElement("w:updateFields")
upd.set(qn("w:val"), "true")
settings.append(upd)

doc.core_properties.title = TITLE
doc.core_properties.author = ", ".join(n for n, _ in TEAM)
doc.save(OUT)
print("saved", OUT)
