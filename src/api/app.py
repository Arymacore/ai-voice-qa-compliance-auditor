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

import hashlib
import hmac
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

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

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

# Browser sign-in: a signed cookie that lasts this many hours.
SESSION_SECONDS = int(os.environ.get("SESSION_HOURS", "8")) * 3600
SESSION_COOKIE = "qa_session"


class LoginBody(BaseModel):
    username: str
    password: str

DASHBOARD_DIR = Path(__file__).resolve().parents[1] / "dashboard"

FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
    '<stop offset="0" stop-color="#a78bfa"/><stop offset="1" stop-color="#6d28d9"/>'
    '</linearGradient></defs>'
    '<rect width="64" height="64" rx="16" fill="url(#g)"/>'
    '<path d="M32 12 L37 27 L52 32 L37 37 L32 52 L27 37 L12 32 L27 27 Z" fill="#fff"/>'
    '</svg>'
)

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
    # auto_error=False: a missing Basic header must not trigger the browser popup.
    basic = HTTPBasic(auto_error=False)
    session_key = hashlib.sha256(b"qa-session|" + password.encode()).digest()

    def check_credentials(given_user: str, given_password: str) -> bool:
        user_ok = secrets.compare_digest(given_user.encode(), user.encode())
        pass_ok = secrets.compare_digest(given_password.encode(), password.encode())
        return user_ok and pass_ok

    def make_session() -> str:
        expires = str(int(time.time()) + SESSION_SECONDS)
        sig = hmac.new(session_key, expires.encode(), hashlib.sha256).hexdigest()
        return f"{expires}.{sig}"

    def session_valid(token: str | None) -> bool:
        if not token or "." not in token:
            return False
        expires, _, sig = token.partition(".")
        good = hmac.new(session_key, expires.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, good) and expires.isdigit() and int(expires) > time.time()

    def is_authed(request: Request, credentials: HTTPBasicCredentials | None) -> bool:
        if session_valid(request.cookies.get(SESSION_COOKIE)):
            return True
        return credentials is not None and check_credentials(
            credentials.username, credentials.password
        )

    def require_login(
        request: Request,
        credentials: Annotated[HTTPBasicCredentials | None, Depends(basic)],
    ) -> None:
        if not is_authed(request, credentials):
            raise HTTPException(status_code=401, detail="Not signed in.")

    def require_page_login(
        request: Request,
        credentials: Annotated[HTTPBasicCredentials | None, Depends(basic)],
    ) -> None:
        if not is_authed(request, credentials):
            raise HTTPException(status_code=303, headers={"Location": "/login"})

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

    @app.get("/", include_in_schema=False, dependencies=[Depends(require_page_login)])
    def dashboard_page():
        return page("index.html", "text/html")

    @app.get("/dashboard.css", include_in_schema=False, dependencies=[Depends(require_page_login)])
    def dashboard_css():
        return page("dashboard.css", "text/css")

    @app.get("/dashboard.js", include_in_schema=False, dependencies=[Depends(require_page_login)])
    def dashboard_js():
        return page("dashboard.js", "text/javascript")

    @app.get("/favicon.svg", include_in_schema=False)
    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return Response(content=FAVICON_SVG, media_type="image/svg+xml")

    @app.get("/login", include_in_schema=False)
    def login_page():
        return page("login.html", "text/html")

    @app.get("/login.css", include_in_schema=False)
    def login_css():
        return page("login.css", "text/css")

    @app.get("/login.js", include_in_schema=False)
    def login_js():
        return page("login.js", "text/javascript")

    @app.post("/login", include_in_schema=False)
    def login(body: LoginBody, request: Request, response: Response):
        if not check_credentials(body.username, body.password):
            raise HTTPException(status_code=401, detail="Incorrect username or password.")
        secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
        response.set_cookie(
            SESSION_COOKIE,
            make_session(),
            max_age=SESSION_SECONDS,
            httponly=True,
            samesite="strict",
            secure=secure,
        )
        return {"status": "ok"}

    @app.get("/logout", include_in_schema=False)
    def logout():
        redirect = RedirectResponse("/login", status_code=303)
        redirect.delete_cookie(SESSION_COOKIE)
        return redirect

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @api.get("/me")
    def me():
        return {"username": user}

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