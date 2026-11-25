"""FastAPI application: JSON API under /api, plus the built React frontend at /."""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .audit import AuditLog
from .auth import COOKIE, LOCAL_ADMIN, AuthError, User, UserStore, required_role
from .autodash import suggest as suggest_dashboard
from .config import Settings, get_settings
from .connections import ConnectionError_
from .database import DatabaseNotFound, DatabaseRegistry, QueryError
from .documents import DocumentError, DocumentNotFound, DocumentStore, Passage
from .history import HistoryStore
from .importer import UploadError
from .llm import LLMError, SQLGenerator, make_generator
from .memory import AgentMemory
from .ratelimit import RateLimiter
from .schemas import (
    AutoDashboardRequest,
    AutoDashboardResponse,
    AutoWidget,
    ConnectRequest,
    DatabaseOut,
    DocAskRequest,
    DocAskResponse,
    DocSource,
    DocumentOut,
    ExecuteRequest,
    ExecuteResponse,
    ExplainRequest,
    ExplainResponse,
    GenerateRequest,
    GenerateResponse,
    HealthOut,
    HistoryItem,
    HistoryUpdate,
    LoginRequest,
    MemoryExampleIn,
    MemoryItemOut,
    MemoryNoteIn,
    NewUser,
    ProfileOut,
    SchemaOut,
    StatsOut,
)
from .seed import SAMPLES_BY_ID, ensure_sample_databases
from .service import answer_question
from .sql_guard import UnsafeSQLError, to_sqlglot_dialect, validate_read_only

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, generator: SQLGenerator | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        ensure_sample_databases(settings.sample_dir)
        registry = DatabaseRegistry(settings)
        registry.refresh()
        app.state.registry = registry
        app.state.history = HistoryStore(settings.app_db_path)
        app.state.documents = DocumentStore(settings.data_dir / "documents.db")
        app.state.memory = AgentMemory(settings.data_dir / "memory.db")
        app.state.audit = AuditLog(settings.data_dir / "audit.db")
        app.state.users = UserStore(settings.data_dir / "users.db", settings.session_hours)
        if settings.auth_enabled:
            _seed_users(app.state.users, settings)
        app.state.generator = generator or make_generator(settings)
        if generator is None:
            if settings.llm_enabled:
                log.info("AI provider: %s (model %s)", settings.provider, settings.active_model)
            else:
                log.warning("No AI API key set (ANTHROPIC_API_KEY or GROQ_API_KEY): "
                            "natural-language questions are disabled.")
        yield

    app = FastAPI(title="Sawaal", version=__version__, lifespan=lifespan)
    app.state.settings = settings

    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    limiter = RateLimiter(settings.rate_limit_per_minute)

    # ---------- error handling ----------

    @app.exception_handler(DatabaseNotFound)
    async def _db_not_found(_: Request, exc: DatabaseNotFound):
        return JSONResponse(status_code=404, content={"detail": f"Database '{exc.args[0]}' not found."})

    @app.exception_handler(UploadError)
    async def _upload_error(_: Request, exc: UploadError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(ConnectionError_)
    async def _connection_error(_: Request, exc: ConnectionError_):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(DocumentError)
    async def _document_error(_: Request, exc: DocumentError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(DocumentNotFound)
    async def _document_missing(_: Request, exc: DocumentNotFound):
        return JSONResponse(status_code=404, content={"detail": "Document not found."})

    @app.exception_handler(LLMError)
    async def _llm_error(_: Request, exc: LLMError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    def registry(request: Request) -> DatabaseRegistry:
        return request.app.state.registry

    def history(request: Request) -> HistoryStore:
        return request.app.state.history

    def user_of(request: Request) -> User:
        return getattr(request.state, "user", None) or LOCAL_ADMIN

    def blocked(request: Request) -> frozenset[str]:
        """Tables this user may not read: the restricted list applies to viewers."""
        return settings.restricted_table_set if user_of(request).role == "viewer" else frozenset()

    def audit(request: Request, action: str, *, database_id: str | None = None, detail: str | None = None,
              status: str = "ok", user: User | None = None) -> None:
        u = user or user_of(request)
        try:
            request.app.state.audit.add(username=u.username, role=u.role, action=action, status=status,
                                        database_id=database_id, detail=detail,
                                        ip=request.client.host if request.client else None)
        except Exception:  # noqa: BLE001 - a full disk must not break answering questions
            log.exception("Could not write the audit log")

    login_limiter = RateLimiter(10)

    @app.middleware("http")
    async def access_control(request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api"):
            return await call_next(request)
        user: User | None = LOCAL_ADMIN
        if settings.auth_enabled:
            user = request.app.state.users.user_for_token(request.cookies.get(COOKIE))
        request.state.user = user
        needed = required_role(request.method, path)
        if needed is not None:
            if user is None:
                return JSONResponse(status_code=401, content={"detail": "Sign in to continue."})
            if not user.can(needed):
                audit(request, "denied", detail=f"{request.method} {path}", status="denied")
                return JSONResponse(
                    status_code=403,
                    content={"detail": f"Your role ({user.role}) can't do this. It needs the {needed} role."},
                )
        return await call_next(request)

    # ---------- meta ----------

    @app.get("/api/health", response_model=HealthOut)
    def health(request: Request):
        llm_enabled = settings.llm_enabled or generator is not None
        return HealthOut(
            llm_enabled=llm_enabled,
            provider=settings.provider,
            model=settings.active_model,
            max_rows=settings.max_rows,
            version=__version__,
        )

    # ---------- databases ----------

    @app.get("/api/databases", response_model=list[DatabaseOut])
    def list_databases(request: Request):
        return [d.to_out() for d in registry(request).list()]

    @app.get("/api/databases/{database_id}/schema", response_model=SchemaOut)
    def get_schema(database_id: str, request: Request):
        schema = registry(request).schema(database_id)
        hide = blocked(request)
        if not hide:
            return schema
        return schema.model_copy(update={"tables": [t for t in schema.tables if t.name.lower() not in hide]})

    @app.get("/api/databases/{database_id}/profile", response_model=ProfileOut)
    def get_profile(database_id: str, request: Request):
        profile = registry(request).profile(database_id)
        hide = blocked(request)
        if not hide:
            return profile
        return profile.model_copy(update={"tables": [t for t in profile.tables if t.name.lower() not in hide]})

    @app.get("/api/databases/{database_id}/examples", response_model=list[str])
    def get_examples(database_id: str, request: Request):
        reg = registry(request)
        info = reg.get(database_id)
        if settings.provider == "demo":
            from .demo import demo_questions

            return demo_questions(info.id)
        if info.kind == "sample" and info.id in SAMPLES_BY_ID:
            return SAMPLES_BY_ID[info.id].questions
        return example_questions(reg.schema(database_id))

    @app.post("/api/databases/upload", response_model=DatabaseOut, status_code=201)
    def upload_database(
        request: Request,
        file: UploadFile = File(...),
        database_id: str | None = Form(default=None),
    ):
        info = registry(request).add_upload(file.filename or "upload.csv", file.file, database_id or None)
        audit(request, "upload_data", database_id=info.id, detail=file.filename)
        return info.to_out()

    @app.post("/api/databases/connect", response_model=DatabaseOut, status_code=201)
    def connect_database(body: ConnectRequest, request: Request):
        info = registry(request).add_connection(body.name, body.url)
        audit(request, "connect_database", database_id=info.id, detail=f"{info.name} ({info.dialect})")
        return info.to_out()

    @app.delete("/api/databases/{database_id}", status_code=204)
    def delete_database(database_id: str, request: Request):
        reg = registry(request)
        audit(request, "delete_database", database_id=database_id, detail=reg.get(database_id).name)
        if reg.get(database_id).saved:
            reg.delete_connection(database_id)
        else:
            reg.delete_upload(database_id)
        history(request).clear(database_id=database_id, keep_starred=False)
        request.app.state.memory.forget_database(database_id)

    # ---------- auto dashboard ----------

    @app.post("/api/databases/{database_id}/auto-dashboard", response_model=AutoDashboardResponse)
    def auto_dashboard(database_id: str, request: Request, body: AutoDashboardRequest | None = None):
        body = body or AutoDashboardRequest()
        use_ai = body.use_ai and (settings.llm_enabled or generator is not None)
        if use_ai:
            wait = limiter.check(request.client.host if request.client else "unknown")
            if wait:
                use_ai = False  # rate limited: still give the rule-based charts
        widgets, source = suggest_dashboard(
            registry(request), database_id, request.app.state.generator, use_ai, body.count, blocked(request)
        )
        audit(request, "suggest_charts", database_id=database_id, detail=f"{len(widgets)} charts ({source})")
        return AutoDashboardResponse(
            database_id=database_id,
            source=source,
            widgets=[AutoWidget(title=w.title, sql=w.sql, note=w.note, result=w.result) for w in widgets],
        )

    # ---------- documents ----------

    def documents(request: Request) -> DocumentStore:
        return request.app.state.documents

    @app.get("/api/documents", response_model=list[DocumentOut])
    def list_documents(request: Request):
        return [DocumentOut(**vars(d)) for d in documents(request).list()]

    @app.post("/api/documents", response_model=DocumentOut, status_code=201)
    def upload_document(request: Request, file: UploadFile = File(...)):
        limit = settings.max_upload_mb * 1024 * 1024
        data = file.file.read(limit + 1)
        if len(data) > limit:
            raise DocumentError(f"The file is larger than {settings.max_upload_mb} MB.")
        doc = documents(request).add(file.filename or "document.txt", data)
        audit(request, "add_document", detail=doc.name)
        return DocumentOut(**vars(doc))

    @app.delete("/api/documents/{document_id}", status_code=204)
    def delete_document(document_id: int, request: Request):
        documents(request).delete(document_id)
        audit(request, "delete_document", detail=str(document_id))

    @app.post("/api/documents/ask", response_model=DocAskResponse)
    def ask_documents(req: DocAskRequest, request: Request):
        audit(request, "ask_documents", database_id=req.database_id, detail=req.question)
        passages: list[Passage] = documents(request).search(req.question, req.document_ids, limit=6)
        sources = [
            DocSource(n=i, document=p.document, page=p.page, text=p.text, score=p.score)
            for i, p in enumerate(passages, start=1)
        ]
        ai_on = settings.llm_enabled or generator is not None
        data_context: str | None = None
        sql: str | None = None
        if ai_on and req.database_id:
            data_context, sql = _database_context(req, request)
            if data_context:
                sources.append(DocSource(n=len(sources) + 1, kind="database", document=registry(request).get(
                    req.database_id).name, text=data_context, score=0.0))
        if not ai_on:
            return DocAskResponse(question=req.question, answer=None, found=bool(sources), sources=sources, sql=sql)
        if not sources:
            return DocAskResponse(
                question=req.question, found=False, sources=[],
                answer="I could not find anything about this in your documents. "
                       "Try other words, or upload the document that covers it.",
            )
        wait = limiter.check(request.client.host if request.client else "unknown")
        if wait:
            raise HTTPException(
                status_code=429,
                detail=f"Too many questions in a short time. Try again in {int(wait) + 1} seconds.",
                headers={"Retry-After": str(int(wait) + 1)},
            )
        out = request.app.state.generator.answer_documents(
            question=req.question, passages=[p.text for p in passages], data_context=data_context
        )
        return DocAskResponse(question=req.question, answer=out.answer, found=out.found, sources=sources, sql=sql)

    def _database_context(req: DocAskRequest, request: Request) -> tuple[str | None, str | None]:
        """Run the question against the chosen database and describe the top of the result as text."""
        from .schemas import GenerateRequest

        try:
            resp = answer_question(
                GenerateRequest(database_id=req.database_id, question=req.question, auto_route=False, insights=False),
                registry(request), request.app.state.generator, settings,
                request.app.state.memory, blocked(request),
            )
        except LLMError:
            return None, None
        r = resp.result
        if not (resp.answerable and r and r.rows):
            return None, None
        lines = [" | ".join(r.columns)] + [" | ".join(str(v) for v in row) for row in r.rows[:15]]
        return "\n".join(lines), resp.sql

    # ---------- queries ----------

    def run_generate(req: GenerateRequest, request: Request, emit=lambda _e, _d: None) -> GenerateResponse:
        if not (settings.llm_enabled or generator is not None):
            raise HTTPException(
                status_code=503,
                detail="Add an API key to the .env file to ask questions in plain English: "
                       "ANTHROPIC_API_KEY for Claude, or GROQ_API_KEY for Groq's free tier. "
                       "You can still write and run SQL yourself.",
            )
        wait = limiter.check(request.client.host if request.client else "unknown")
        if wait:
            raise HTTPException(
                status_code=429,
                detail=f"Too many questions in a short time. Try again in {int(wait) + 1} seconds.",
                headers={"Retry-After": str(int(wait) + 1)},
            )
        reg = registry(request)
        started = time.perf_counter()
        user = user_of(request)
        response = answer_question(
            req, reg, request.app.state.generator, settings,
            memory=request.app.state.memory, blocked=blocked(request), emit=emit, user=user.username,
        )
        if response.answerable and response.sql:
            response.history_id = history(request).add(
                database_id=response.database_id,
                question=req.question,
                sql=response.sql,
                explanation=response.explanation,
                row_count=response.result.row_count if response.result else None,
                error=response.error,
                source="ai",
                repairs=len(response.attempts),
                elapsed_ms=(time.perf_counter() - started) * 1000,
            )
        outcome = "error" if response.error else "ok" if response.answerable else "unanswerable"
        audit(request, "ask", database_id=response.database_id, status=outcome,
              detail=f"{req.question} | {response.sql}" if response.sql else req.question, user=user)
        return response

    @app.post("/api/generate", response_model=GenerateResponse)
    def generate(req: GenerateRequest, request: Request):
        return run_generate(req, request)

    @app.post("/api/generate/stream")
    def generate_stream(req: GenerateRequest, request: Request):
        """Same as /api/generate, but sends progress as server-sent events so the page can show each step."""
        events: queue.Queue[tuple[str, dict] | None] = queue.Queue()

        def work() -> None:
            try:
                response = run_generate(req, request, lambda name, data: events.put((name, data)))
                events.put(("done", json.loads(response.model_dump_json())))
            except HTTPException as e:
                events.put(("error", {"detail": e.detail, "status": e.status_code}))
            except LLMError as e:
                events.put(("error", {"detail": e.message, "status": e.status_code}))
            except DatabaseNotFound as e:
                events.put(("error", {"detail": f"Database '{e.args[0]}' not found.", "status": 404}))
            except Exception:  # noqa: BLE001
                log.exception("Streaming answer failed")
                events.put(("error", {"detail": "Something went wrong while answering.", "status": 500}))
            finally:
                events.put(None)

        threading.Thread(target=work, daemon=True).start()

        def stream():
            while True:
                item = events.get()
                if item is None:
                    return
                yield f"event: {item[0]}\ndata: {json.dumps(item[1])}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/execute", response_model=ExecuteResponse)
    def execute(req: ExecuteRequest, request: Request):
        reg = registry(request)
        reg.get(req.database_id)
        try:
            sql, result = reg.execute(req.database_id, req.sql, blocked(request))
            response = ExecuteResponse(sql=sql, result=result)
        except (UnsafeSQLError, QueryError) as e:
            response = ExecuteResponse(sql=req.sql.strip(), error=str(e))
        if req.save_to_history or response.error:
            audit(request, "run_sql", database_id=req.database_id, detail=req.sql.strip(),
                  status="error" if response.error else "ok")
        if req.save_to_history:
            response.history_id = history(request).add(
                database_id=req.database_id,
                question=req.question,
                sql=response.sql,
                row_count=response.result.row_count if response.result else None,
                error=response.error,
                source="manual",
            )
        return response

    @app.post("/api/explain", response_model=ExplainResponse)
    def explain(req: ExplainRequest, request: Request):
        if not (settings.llm_enabled or generator is not None):
            raise HTTPException(status_code=503, detail="Add an API key to the .env file to get explanations.")
        wait = limiter.check(request.client.host if request.client else "unknown")
        if wait:
            raise HTTPException(
                status_code=429,
                detail=f"Too many requests in a short time. Try again in {int(wait) + 1} seconds.",
                headers={"Retry-After": str(int(wait) + 1)},
            )
        reg = registry(request)
        info = reg.get(req.database_id)
        schema = reg.schema_prompt(info.id, hide=blocked(request))
        out = request.app.state.generator.explain(dialect=info.dialect, schema=schema, sql=req.sql)
        return ExplainResponse(summary=out.summary, steps=out.steps)

    # ---------- sign-in, users, audit ----------

    @app.get("/api/auth/me")
    def me(request: Request):
        user = user_of(request) if not settings.auth_enabled else request.state.user
        return {
            "auth_enabled": settings.auth_enabled,
            "user": {"username": user.username, "role": user.role} if user else None,
            "restricted_tables": sorted(settings.restricted_table_set) if user and user.role == "viewer" else [],
        }

    @app.post("/api/auth/login")
    def login(body: LoginRequest, request: Request, response: Response):
        if not settings.auth_enabled:
            return {"auth_enabled": False, "user": {"username": LOCAL_ADMIN.username, "role": LOCAL_ADMIN.role}}
        key = f"{request.client.host if request.client else '?'}:{body.username.lower()}"
        wait = login_limiter.check(key)
        if wait:
            raise HTTPException(
                status_code=429, detail=f"Too many sign-in attempts. Try again in {int(wait) + 1} seconds."
            )
        try:
            user, token = request.app.state.users.login(body.username, body.password)
        except AuthError as e:
            audit(request, "login", status="denied", detail=body.username[:40], user=User(0, "anonymous", "viewer"))
            raise HTTPException(status_code=401, detail=str(e)) from e
        response.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=settings.session_hours * 3600)
        audit(request, "login", user=user)
        return {"auth_enabled": True, "user": {"username": user.username, "role": user.role}}

    @app.post("/api/auth/logout", status_code=204)
    def logout(request: Request, response: Response):
        if settings.auth_enabled:
            request.app.state.users.logout(request.cookies.get(COOKIE))
            if getattr(request.state, "user", None):
                audit(request, "logout")
        response.delete_cookie(COOKIE)

    @app.get("/api/users")
    def list_users(request: Request):
        return request.app.state.users.list()

    @app.post("/api/users", status_code=201)
    def create_user(body: NewUser, request: Request):
        try:
            user = request.app.state.users.create(body.username, body.password, body.role)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        audit(request, "create_user", detail=f"{user.username} ({user.role})")
        return {"id": user.id, "username": user.username, "role": user.role}

    @app.delete("/api/users/{user_id}", status_code=204)
    def delete_user(user_id: int, request: Request):
        try:
            if not request.app.state.users.delete(user_id):
                raise HTTPException(status_code=404, detail="User not found.")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        audit(request, "delete_user", detail=str(user_id))

    @app.get("/api/audit")
    def get_audit(request: Request, limit: int = Query(default=200, ge=1, le=1000), action: str | None = None,
                  username: str | None = None):
        return request.app.state.audit.list(limit=limit, action=action, username=username)

    # ---------- training (agent memory) ----------

    @app.get("/api/memory", response_model=list[MemoryItemOut])
    def list_memory(request: Request, database_id: str | None = None):
        return [MemoryItemOut(**vars(i)) for i in request.app.state.memory.list(database_id)]

    @app.post("/api/memory/examples", response_model=MemoryItemOut, status_code=201)
    def teach_example(body: MemoryExampleIn, request: Request):
        info = registry(request).get(body.database_id)
        try:  # only SQL that passes the read-only check can be taught
            sql = validate_read_only(body.sql, to_sqlglot_dialect(info.dialect))
        except UnsafeSQLError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        item = request.app.state.memory.add_example(info.id, body.question, sql, user_of(request).username)
        audit(request, "teach_example", database_id=info.id, detail=body.question)
        return MemoryItemOut(**vars(item))

    @app.post("/api/memory/notes", response_model=MemoryItemOut, status_code=201)
    def teach_note(body: MemoryNoteIn, request: Request):
        info = registry(request).get(body.database_id)
        item = request.app.state.memory.add_note(info.id, body.text, user_of(request).username)
        audit(request, "teach_note", database_id=info.id, detail=body.text)
        return MemoryItemOut(**vars(item))

    @app.delete("/api/memory/{item_id}", status_code=204)
    def forget(item_id: int, request: Request):
        if not request.app.state.memory.delete(item_id):
            raise HTTPException(status_code=404, detail="Nothing to forget with that id.")
        audit(request, "forget", detail=str(item_id))

    # ---------- history ----------

    @app.get("/api/history", response_model=list[HistoryItem])
    def list_history(
        request: Request,
        database_id: str | None = None,
        starred: bool = False,
        limit: int = Query(default=100, ge=1, le=500),
    ):
        return history(request).list(database_id=database_id, starred_only=starred, limit=limit)

    @app.get("/api/stats", response_model=StatsOut)
    def get_stats(request: Request, database_id: str | None = None):
        return history(request).stats(database_id)

    @app.patch("/api/history/{item_id}", response_model=HistoryItem)
    def update_history(item_id: int, body: HistoryUpdate, request: Request):
        item = history(request).set_starred(item_id, body.starred)
        if item is None:
            raise HTTPException(status_code=404, detail="History item not found.")
        return item

    @app.delete("/api/history/{item_id}", status_code=204)
    def delete_history(item_id: int, request: Request):
        if not history(request).delete(item_id):
            raise HTTPException(status_code=404, detail="History item not found.")

    @app.delete("/api/history", status_code=204)
    def clear_history(request: Request, database_id: str | None = None):
        history(request).clear(database_id=database_id, keep_starred=True)

    # ---------- frontend ----------

    dist: Path = settings.frontend_dist
    if (dist / "index.html").exists():
        if (dist / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not found")
            candidate = (dist / path).resolve()
            if path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app


DEMO_PASSWORDS = {"admin": "admin-demo", "analyst": "analyst-demo", "viewer": "viewer-demo"}


def _seed_users(users: UserStore, settings: Settings) -> None:
    """Make sure a first admin exists when sign-in is on."""
    if settings.demo_users:
        for role, password in DEMO_PASSWORDS.items():
            if not any(u["username"] == role for u in users.list()):
                users.create(role, settings.admin_password if role == "admin" and settings.admin_password
                             else password, role)
        log.warning("Demo users created (admin, analyst, viewer). Do not use DEMO_USERS outside a demonstration.")
        return
    if users.count() == 0:
        import secrets

        password = settings.admin_password or secrets.token_urlsafe(9)
        users.create("admin", password, "admin")
        if not settings.admin_password:
            log.warning("First start with sign-in on. Admin login: admin / %s  (shown once; set ADMIN_PASSWORD "
                        "in .env to choose your own)", password)


def example_questions(schema: SchemaOut, limit: int = 6) -> list[str]:
    """Simple starter questions for an uploaded database, built from its schema (no LLM call)."""
    questions: list[str] = []
    for t in schema.tables:
        if t.kind != "table":
            continue
        numeric = [c.name for c in t.columns
                   if any(k in c.type.upper() for k in ("INT", "REAL", "NUM", "DEC", "FLOAT", "DOUBLE"))
                   and not c.primary_key and not c.foreign_key and not c.name.lower().endswith("id")]
        categorical = [c.name for c in t.columns if c.values]
        if numeric and categorical:
            questions.append(f"What is the average {numeric[0]} for each {categorical[0]} in {t.name}?")
        elif categorical:
            questions.append(f"How many {t.name} rows are there for each {categorical[0]}?")
        if numeric:
            questions.append(f"Show the 10 {t.name} rows with the highest {numeric[0]}")
        questions.append(f"How many rows are in {t.name}?")
    seen: set[str] = set()
    unique = [q for q in questions if not (q in seen or seen.add(q))]
    return unique[:limit]


app = create_app()
