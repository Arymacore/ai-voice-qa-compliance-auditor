"""
test_dashboard.py

Tests that the dashboard is served only to logged-in users, that every response
carries the security headers, and static guards that keep the page free of
inline code and of the DOM APIs that turn untrusted text into executable markup.
"""

import base64
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api.app import DASHBOARD_DIR, create_app
from src.storage import Store

AUTH = {"Authorization": "Basic " + base64.b64encode(b"reviewer:capstone_group9").decode()}


@pytest.fixture
def client(tmp_path):
    store = Store(f"sqlite:///{(tmp_path / 'd.db').as_posix()}")
    yield TestClient(create_app(store=store, user="reviewer", password="capstone_group9", use_llm=False))
    store.close()


@pytest.mark.parametrize("path", ["/", "/dashboard.css", "/dashboard.js"])
def test_dashboard_files_require_login(client, path):
    resp = client.get(path, follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/login"


def test_page_is_served_to_a_logged_in_user(client):
    r = client.get("/", headers=AUTH)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "AI Voice QA" in r.text


def test_script_and_stylesheet_have_the_right_types(client):
    js = client.get("/dashboard.js", headers=AUTH)
    css = client.get("/dashboard.css", headers=AUTH)
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")


@pytest.mark.parametrize("path", ["/", "/api/health", "/api/summary"])
def test_security_headers_are_on_pages_and_api_responses(client, path):
    r = client.get(path, headers=AUTH)
    csp = r.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp and "connect-src 'self'" in csp
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"


def test_security_headers_are_also_on_login_failures(client):
    r = client.get("/api/summary")
    assert r.status_code == 401 and "content-security-policy" in r.headers


def test_page_has_no_inline_script_style_or_event_handlers():
    html = (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)  # every script tag loads a file
    assert not re.search(r"\son\w+\s*=", html)  # no onclick= and friends
    assert 'style="' not in html and "<style" not in html


def test_script_never_turns_untrusted_text_into_markup():
    js = (DASHBOARD_DIR / "dashboard.js").read_text(encoding="utf-8")
    for banned in ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"]:
        assert banned not in js, f"dashboard.js must not use {banned}"