"""Tests that uploads are rate limited."""

import base64
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.api.app as app_module
from src.api.app import create_app
from src.storage import Store

AUTH = {"Authorization": "Basic " + base64.b64encode(b"reviewer:capstone_group9").decode()}


def test_uploads_are_rate_limited(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "UPLOADS_PER_HOUR", 2)
    store = Store(f"sqlite:///{(tmp_path / 'r.db').as_posix()}")
    client = TestClient(create_app(store=store, user="reviewer", password="capstone_group9", use_llm=False))
    text = b"Agent: This call may be recorded. My name is Sam, and this is an attempt to collect a debt.\n"
    codes = [
        client.post("/api/calls/analyze", headers=AUTH, files={"file": ("t.txt", text)}).status_code
        for _ in range(3)
    ]
    assert codes == [201, 201, 429]
    store.close()