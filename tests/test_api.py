"""
test_api.py

Tests for the FastAPI backend: login, listing/filtering, detail, delete, and the
upload-and-analyze endpoint including hostile input. Each test gets its own
throwaway SQLite database, and no test calls the real OpenAI API.
"""

import base64
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api.app import create_app
from src.detection.rules import ALL_RULES
from src.detection.tone import DIMENSIONS
from src.scoring.analysis import analyze_folder
from src.storage import Store

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "sample"
CLEAN = SAMPLE_DIR / "call_001_compliant.txt"
BAD = SAMPLE_DIR / "call_002_noncompliant.txt"
AUTH = {"Authorization": "Basic " + base64.b64encode(b"reviewer:s3cret-pass").decode()}


@pytest.fixture
def store(tmp_path):
    s = Store(f"sqlite:///{(tmp_path / 'api.db').as_posix()}")
    yield s
    s.close()


@pytest.fixture
def client(store):
    return TestClient(create_app(store=store, user="reviewer", password="s3cret-pass", use_llm=False))


@pytest.fixture
def loaded(client, store, tmp_path):
    """A client whose database already holds a few analyzed calls."""
    import shutil
    folder = tmp_path / "calls"
    folder.mkdir()
    shutil.copy(CLEAN, folder / "a_clean.txt")
    shutil.copy(BAD, folder / "b_bad.txt")
    store.save_many(analyze_folder(folder, use_llm=False))
    return client


def upload(client, name, data, headers=AUTH):
    return client.post("/api/calls/analyze", files={"file": (name, data, "text/plain")}, headers=headers)


# ---------- login ----------

def test_health_needs_no_login(client):
    assert client.get("/api/health").json() == {"status": "ok"}


@pytest.mark.parametrize("method,url", [
    ("get", "/api/summary"), ("get", "/api/calls"), ("get", "/api/calls/x"),
    ("delete", "/api/calls/x"), ("post", "/api/calls/analyze"),
])
def test_every_other_endpoint_requires_login(client, method, url):
    assert getattr(client, method)(url).status_code == 401


def test_wrong_password_is_rejected_without_a_popup(client):
    bad = {"Authorization": "Basic " + base64.b64encode(b"reviewer:wrong").decode()}
    r = client.get("/api/summary", headers=bad)
    assert r.status_code == 401 and "www-authenticate" not in r.headers


def test_correct_login_is_accepted(client):
    assert client.get("/api/summary", headers=AUTH).status_code == 200


def test_app_refuses_to_start_without_credentials(store):
    with pytest.raises(RuntimeError, match="DASHBOARD_USER"):
        create_app(store=store, user="", password="")


def test_credentials_can_come_from_the_environment(store, monkeypatch):
    monkeypatch.setenv("DASHBOARD_USER", "envuser")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "envpass")
    c = TestClient(create_app(store=store, use_llm=False))
    good = {"Authorization": "Basic " + base64.b64encode(b"envuser:envpass").decode()}
    assert c.get("/api/summary", headers=good).status_code == 200


def test_api_docs_are_off_by_default(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


# ---------- reading ----------

def test_summary_reflects_stored_calls(loaded):
    s = loaded.get("/api/summary", headers=AUTH).json()
    assert s["total"] == 2 and s["by_status"] == {"PASS": 1, "REVIEW": 0, "FAIL": 1}


def test_list_filters(loaded):
    rows = loaded.get("/api/calls?needs_review=true", headers=AUTH).json()
    assert [r["call_id"] for r in rows] == ["b_bad"]
    rows = loaded.get("/api/calls?status=PASS", headers=AUTH).json()
    assert [r["call_id"] for r in rows] == ["a_clean"]
    assert "transcript" not in rows[0]


@pytest.mark.parametrize("query", ["status=MAYBE", "limit=0", "limit=501", "offset=-1"])
def test_invalid_query_values_are_rejected(loaded, query):
    assert loaded.get(f"/api/calls?{query}", headers=AUTH).status_code == 422


def test_detail_returns_the_full_result(loaded):
    r = loaded.get("/api/calls/b_bad", headers=AUTH).json()
    assert r["compliance"]["status"] == "FAIL" and "Agent:" in r["transcript"]


def test_unknown_call_is_404(loaded):
    assert loaded.get("/api/calls/nope", headers=AUTH).status_code == 404


def test_delete_then_gone(loaded):
    assert loaded.delete("/api/calls/b_bad", headers=AUTH).status_code == 204
    assert loaded.get("/api/calls/b_bad", headers=AUTH).status_code == 404
    assert loaded.delete("/api/calls/b_bad", headers=AUTH).status_code == 404


# ---------- uploading ----------

def test_upload_analyzes_stores_and_hides_server_paths(client):
    r = upload(client, "call_002_noncompliant.txt", BAD.read_bytes())
    body = r.json()
    assert r.status_code == 201
    assert body["compliance"]["status"] == "FAIL" and body["compliance"]["engine"] == "regex"
    assert body["call_id"].startswith("call_002_noncompliant-")
    assert body["source_file"] == "call_002_noncompliant.txt"
    assert client.get(f"/api/calls/{body['call_id']}", headers=AUTH).status_code == 200


def test_uploading_the_same_file_twice_makes_two_records(client):
    a = upload(client, "same.txt", CLEAN.read_bytes()).json()["call_id"]
    b = upload(client, "same.txt", CLEAN.read_bytes()).json()["call_id"]
    assert a != b and client.get("/api/summary", headers=AUTH).json()["total"] == 2


def test_hostile_filename_is_neutralized(client):
    body = upload(client, "../../etc/evil name!.txt", CLEAN.read_bytes()).json()
    assert body["source_file"] == "evil_name.txt"
    assert body["call_id"].startswith("evil_name-")
    assert "/" not in body["call_id"] and ".." not in body["call_id"]


def test_unsupported_file_type_is_415(client):
    assert upload(client, "call.pdf", b"%PDF-1.4").status_code == 415


def test_oversized_upload_is_413(client, monkeypatch):
    monkeypatch.setattr("src.api.app.MAX_FILE_SIZE_BYTES", 10)
    assert upload(client, "big.txt", b"x" * 11).status_code == 413


def test_empty_upload_is_422(client):
    r = upload(client, "empty.txt", b"")
    assert r.status_code == 422 and "empty" in r.json()["detail"]


def test_non_utf8_text_is_422_not_a_crash(client):
    r = upload(client, "weird.txt", b"\xff\xfe\x00bad bytes \x80\x81")
    assert r.status_code == 422


def test_failed_uploads_store_nothing(client):
    upload(client, "empty.txt", b"")
    upload(client, "call.pdf", b"x")
    assert client.get("/api/summary", headers=AUTH).json()["total"] == 0


def test_upload_requires_a_file(client):
    assert client.post("/api/calls/analyze", headers=AUTH).status_code == 422


def test_upload_can_use_the_llm_layer(store):
    def reply(user):
        if user.startswith("RULES:"):
            body = {r.rule_id: {"satisfied": True, "evidence": None} for r in ALL_RULES}
            return json.dumps({"results": body})
        quote = "this call may be recorded for quality assurance purposes"
        return json.dumps({"ratings": {d: {"score": 4, "evidence": quote} for d in DIMENSIONS}})

    class Completions:
        def create(self, **kw):
            msg = SimpleNamespace(content=reply(kw["messages"][1]["content"]))
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    fake = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    c = TestClient(create_app(store=store, user="reviewer", password="s3cret-pass", llm_client=fake))
    body = upload(c, "clean.txt", CLEAN.read_bytes()).json()
    assert body["compliance"]["engine"] == "hybrid" and body["tone"]["flag"] == "OK"