"""Vercel entry point: serves the FastAPI backend as a serverless function.

vercel.json rewrites every /api/... request to this function and passes the original path in the `__p` query
parameter, which is put back here so the backend sees the real URL.

The filesystem is read-only except /tmp, so data is kept there. It is cleared whenever the function is recycled,
which is fine for a demonstration (sample databases are rebuilt on start) but not for real use.
"""

import os
import sys
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode

os.environ.setdefault("DATA_DIR", "/tmp/sawaal")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.main import app as backend  # noqa: E402


async def app(scope, receive, send):
    if scope["type"] in ("http", "websocket"):
        pairs = parse_qsl(scope.get("query_string", b"").decode(), keep_blank_values=True)
        original = next((v for k, v in pairs if k == "__p"), None)
        if original is not None:
            rest = urlencode([(k, v) for k, v in pairs if k != "__p"])
            path = "/api/" + unquote(original).lstrip("/")
            scope = dict(scope, path=path, raw_path=path.encode(), query_string=rest.encode())
    await backend(scope, receive, send)
