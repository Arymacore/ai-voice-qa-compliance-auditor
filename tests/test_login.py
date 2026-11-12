"""Tests for the browser login page and session cookie."""

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api.app import create_app
from src.storage import Store

USER, PW = "reviewer", "test-password-only"


def make_client(tmp_path):
    store = Store(f"sqlite:///{(tmp_path / 'l.db').as_posix()}")
    return TestClient(create_app(store=store, user=USER, password=PW, use_llm=False)), store


def test_dashboard_redirects_to_login(tmp_path):
    client, store = make_client(tmp_path)
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"
    store.close()


def test_login_page_is_public(tmp_path):
    client, store = make_client(tmp_path)
    assert client.get("/login").status_code == 200
    assert client.get("/login.js").status_code == 200
    assert client.get("/login.css").status_code == 200
    store.close()


def test_api_without_login_is_401_without_popup_header(tmp_path):
    client, store = make_client(tmp_path)
    resp = client.get("/api/summary")
    assert resp.status_code == 401
    assert "www-authenticate" not in resp.headers
    store.close()


def test_wrong_password_rejected(tmp_path):
    client, store = make_client(tmp_path)
    resp = client.post("/login", json={"username": USER, "password": "nope"})
    assert resp.status_code == 401
    assert client.get("/api/summary").status_code == 401
    store.close()


def test_login_then_logout(tmp_path):
    client, store = make_client(tmp_path)
    assert client.post("/login", json={"username": USER, "password": PW}).status_code == 200
    assert client.get("/api/summary").status_code == 200
    assert client.get("/", follow_redirects=False).status_code == 200
    client.get("/logout", follow_redirects=False)
    assert client.get("/api/summary").status_code == 401
    store.close()


def test_tampered_cookie_rejected(tmp_path):
    client, store = make_client(tmp_path)
    client.cookies.set("qa_session", "9999999999.not-a-real-signature")
    assert client.get("/api/summary").status_code == 401
    store.close()


def test_basic_header_still_works(tmp_path):
    client, store = make_client(tmp_path)
    assert client.get("/api/summary", auth=(USER, PW)).status_code == 200
    store.close()


def test_dashboard_has_logout_link(tmp_path):
    client, store = make_client(tmp_path)
    client.post("/login", json={"username": USER, "password": PW})
    assert 'href="/logout"' in client.get("/").text
    store.close()


def test_me_requires_login_and_returns_username(tmp_path):
    client, store = make_client(tmp_path)
    assert client.get("/api/me").status_code == 401
    client.post("/login", json={"username": USER, "password": PW})
    resp = client.get("/api/me")
    assert resp.status_code == 200
    assert resp.json() == {"username": USER}
    store.close()


def test_dashboard_has_account_menu(tmp_path):
    client, store = make_client(tmp_path)
    client.post("/login", json={"username": USER, "password": PW})
    page = client.get("/").text
    assert 'id="user-menu-button"' in page
    assert 'href="/logout"' in page
    store.close()


def test_favicon_is_public(tmp_path):
    client, store = make_client(tmp_path)
    resp = client.get("/favicon.svg")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")
    assert client.get("/favicon.ico").status_code == 200
    store.close()
