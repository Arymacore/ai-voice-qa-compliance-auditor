"""
app.py

FastAPI backend: serves stored analysis results and analyzes newly uploaded calls.

Run locally (from the project root):
    python -m uvicorn src.api.app:create_app --factory --reload

Configuration (environment variables or the .env file):
    DASHBOARD_USER, DASHBOARD_PASSWORD   REQUIRED. The app refuses to start without
                                         them (secure by default).
    DATABASE_URL                         optional; defaults to a local SQLite file
    OPENAI_API_KEY                       optional; without it uploads use regex only
    ENABLE_API_DOCS=1                    optional; turns on /docs (off by default)

Endpoints (everything except /api/health requires HTTP Basic login):
    GET    /api/health                   liveness check, no login needed
    GET    /api/summary                  headline counts
    GET    /api/calls                    list; filters: needs_review, status, limit, offset
    GET    /api/calls/{call_id}          one full result, including the transcript
    POST   /api/calls/analyze            upload a call file, analyze it, store it
    DELETE /api/calls/{call_id}          remove a stored call

Note: HTTP Basic sends the password with every request, so it must only be used
over HTTPS once deployed (the cloud load balancer provides this).
"""

import logging
import os
import re
import secrets
import tempfile
import time
import uuid
from pathlib import Path
from collections import deque
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from src.ingestion.file_validator import (
    MAX_FILE_SIZE_BYTES,
    SUPPORTED_AUDIO_EXTENSIONS,
    SUPPORTED_TEXT_EXTENSIONS,
)
from src.ingestion.pipeline import IngestionError
from src.scoring.analysis import analyze_call
from src.storage import Store

logger = logging.getLogger(__name__)

_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")

# Uploads call a paid API, so cap how many can be analyzed per hour.
UPLOADS_PER_HOUR = int(os.environ.get("UPLOADS_PER_HOUR", "20"))

DASHBOARD_DIR = Path(__file__).resolve().parents[1] / "dashboard"

# Sent on every response. The dashboard loads only its own script and stylesheet,
# so scripts, styles, and connections are restricted to this origin; the page
# cannot be framed, and API responses (which contain transcripts) are never cached.
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def _clean_filename(filename: str | None) -> tuple[str, str]:
    """Return a safe (stem, extension) from a client-supplied filename.

    The client controls this string, so drop any directory parts and every
    character outside a small safe set before it is used anywhere.
    """
    name = Path((filename or "").replace("\\", "/")).name
    stem = _UNSAFE_NAME_CHARS.sub("_", Path(name).stem).strip("._")[:60] or "upload"
    return stem, Path(name).suffix.lower()


def create_app(
    store: Store | None = None,
    user: str | None = None,
    password: str | None = None,
    use_llm: bool = True,
    llm_client=None,
    enable_docs: bool | None = None,
) -> FastAPI:
    if user is None and password is None:
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
        user = os.environ.get("DASHBOARD_USER")
        password = os.environ.get("DASHBOARD_PASSWORD")
    if not user or not password:
        raise RuntimeError(
            "DASHBOARD_USER and DASHBOARD_PASSWORD must both be set (in .env or the "
            "environment). The app will not start without a login configured."
        )
    if enable_docs is None:
        enable_docs = os.environ.get("ENABLE_API_DOCS") == "1"

    store = store or Store()
    app = FastAPI(
        title="AI Voice QA & Compliance Auditor",
        version="0.3.0",
        docs_url="/docs" if enable_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if enable_docs else None,
    )
    basic = HTTPBasic()

    def require_login(credentials: Annotated[HTTPBasicCredentials, Depends(basic)]) -> None:
        user_ok = secrets.compare_digest(credentials.username.encode(), user.encode())
        pass_ok = secrets.compare_digest(credentials.password.encode(), password.encode())
        if not (user_ok and pass_ok):
            raise HTTPException(
                status_code=401,
                detail="Incorrect username or password.",
                headers={"WWW-Authenticate": "Basic"},
            )

    api = APIRouter(prefix="/api", dependencies=[Depends(require_login)])

    upload_times: deque = deque()

    def limit_uploads() -> None:
        now = time.monotonic()
        while upload_times and now - upload_times[0] > 3600:
            upload_times.popleft()
        if len(upload_times) >= UPLOADS_PER_HOUR:
            raise HTTPException(status_code=429, detail="Upload limit reached. Try again later.")
        upload_times.append(now)

    @app.middleware("http")
    async def add_security_headers(request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        return response

    def page(filename: str, media_type: str):
        return FileResponse(DASHBOARD_DIR / filename, media_type=media_type)

    @app.get("/", include_in_schema=False, dependencies=[Depends(require_login)])
    def dashboard_page():
        return page("index.html", "text/html")

    @app.get("/dashboard.css", include_in_schema=False, dependencies=[Depends(require_login)])
    def dashboard_css():
        return page("dashboard.css", "text/css")

    @app.get("/dashboard.js", include_in_schema=False, dependencies=[Depends(require_login)])
    def dashboard_js():
        return page("dashboard.js", "text/javascript")

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @api.get("/summary")
    def summary():
        return store.summary()

    @api.get("/calls")
    def list_calls(
        needs_review: bool | None = None,
        status_filter: Annotated[
            str | None, Query(alias="status", pattern="^(PASS|REVIEW|FAIL)$")
        ] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ):
        return store.list(
            needs_review=needs_review, status=status_filter, limit=limit, offset=offset
        )

    @api.get("/calls/{call_id}")
    def get_call(call_id: str):
        result = store.get(call_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Call not found.")
        return result

    @api.delete("/calls/{call_id}", status_code=204)
    def delete_call(call_id: str):
        if not store.delete(call_id):
            raise HTTPException(status_code=404, detail="Call not found.")
        return Response(status_code=204)

    @api.post("/calls/analyze", status_code=201, dependencies=[Depends(limit_uploads)])
    def analyze_upload(file: UploadFile):
        stem, ext = _clean_filename(file.filename)
        supported = SUPPORTED_AUDIO_EXTENSIONS | SUPPORTED_TEXT_EXTENSIONS
        if ext not in supported:
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported file type '{ext}'. Supported: {sorted(supported)}",
            )
        data = file.file.read(MAX_FILE_SIZE_BYTES + 1)
        if len(data) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(status_code=413, detail="File is too large.")

        # A random suffix keeps repeat uploads of the same name from overwriting each other.
        call_id = f"{stem}-{uuid.uuid4().hex[:6]}"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"{call_id}{ext}"
            path.write_bytes(data)
            try:
                result = analyze_call(path, use_llm=use_llm, llm_client=llm_client)
            except IngestionError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except UnicodeDecodeError as exc:
                raise HTTPException(status_code=422, detail="File is not valid UTF-8 text.") from exc
            except Exception as exc:
                logger.exception("Analysis failed for upload %s", call_id)
                raise HTTPException(status_code=500, detail="Analysis failed.") from exc

        result["source_file"] = f"{stem}{ext}"  # never expose the server's temp path
        store.save(result)
        return result

    app.include_router(api)
    return app