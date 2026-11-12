"""
test_storage.py

Tests for the database layer. Each test uses its own throwaway SQLite file.
"""

import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.scoring.analysis import analyze_call, analyze_folder, main
from src.storage import Store, default_url

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "sample"
CLEAN = SAMPLE_DIR / "call_001_compliant.txt"
BAD = SAMPLE_DIR / "call_002_noncompliant.txt"


@pytest.fixture
def store(tmp_path):
    s = Store(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    yield s
    s.close()


def result(call_id, analyzed_at="2026-10-27T10:00:00+00:00", status="PASS", needs_review=False):
    return {
        "schema_version": 1,
        "call_id": call_id,
        "source_file": f"data/sample/{call_id}.txt",
        "analyzed_at": analyzed_at,
        "needs_review": needs_review,
        "review_reasons": [f"compliance {status}"] if status != "PASS" else [],
        "compliance": {"status": status, "score": 100 if status == "PASS" else 0, "rules": []},
        "tone": {"flag": "OK", "score": 80, "ratings": []},
        "transcript": "Agent: hello",
    }


def test_full_result_round_trips_exactly(store):
    original = analyze_call(BAD, use_llm=False)
    store.save(original)
    assert store.get("call_002_noncompliant") == original


def test_saving_the_same_call_again_replaces_it(store):
    store.save(result("a", status="PASS"))
    store.save(result("a", status="FAIL", needs_review=True))
    assert len(store.list()) == 1
    assert store.get("a")["compliance"]["status"] == "FAIL"


def test_list_is_newest_first_and_supports_paging(store):
    store.save_many([
        result("old", "2026-10-25T10:00:00+00:00"),
        result("new", "2026-10-27T10:00:00+00:00"),
        result("mid", "2026-10-26T10:00:00+00:00"),
    ])
    assert [r["call_id"] for r in store.list()] == ["new", "mid", "old"]
    assert [r["call_id"] for r in store.list(limit=1, offset=1)] == ["mid"]


def test_list_filters_by_review_flag_and_status(store):
    store.save_many([
        result("ok", status="PASS"),
        result("bad", status="FAIL", needs_review=True),
        result("meh", status="REVIEW", needs_review=True),
    ])
    assert {r["call_id"] for r in store.list(needs_review=True)} == {"bad", "meh"}
    assert [r["call_id"] for r in store.list(needs_review=False)] == ["ok"]
    assert [r["call_id"] for r in store.list(status="FAIL")] == ["bad"]


def test_list_rows_are_lightweight(store):
    store.save(result("a", status="FAIL", needs_review=True))
    row = store.list()[0]
    assert "transcript" not in row and "compliance" not in row
    assert row["compliance_status"] == "FAIL"
    assert row["review_reasons"] == ["compliance FAIL"]


def test_unreadable_call_entries_are_stored_with_their_error(store):
    store.save({"schema_version": 1, "call_id": "broken", "source_file": "x.txt", "error": "File is empty."})
    row = store.list()[0]
    assert row["error"] == "File is empty." and row["needs_review"] is False
    assert store.get("broken")["error"] == "File is empty."


def test_summary_counts(store):
    store.save_many([
        result("a", status="PASS"),
        result("b", status="FAIL", needs_review=True),
        {"schema_version": 1, "call_id": "c", "source_file": "c.txt", "error": "bad"},
    ])
    s = store.summary()
    assert s["total"] == 3 and s["analyzed"] == 2 and s["errors"] == 1
    assert s["by_status"] == {"PASS": 1, "REVIEW": 0, "FAIL": 1}
    assert s["needs_review"] == 1


def test_get_missing_returns_none_and_delete_reports_whether_it_existed(store):
    assert store.get("nope") is None
    store.save(result("a"))
    assert store.delete("a") is True
    assert store.delete("a") is False


@pytest.mark.parametrize("bad", [{}, {"call_id": ""}, {"call_id": "   "}, {"call_id": 5}])
def test_result_without_a_usable_call_id_is_rejected(store, bad):
    with pytest.raises(ValueError):
        store.save(bad)


def test_one_bad_result_in_a_batch_saves_nothing(store):
    with pytest.raises(ValueError):
        store.save_many([result("good"), {"no": "call_id"}])
    assert store.list() == []


def test_data_survives_reopening_the_database(tmp_path):
    url = f"sqlite:///{(tmp_path / 'persist.db').as_posix()}"
    first = Store(url)
    first.save(result("a"))
    first.close()
    assert Store(url).get("a")["call_id"] == "a"


def test_store_can_be_used_from_several_threads(store):
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: store.save(result(f"call_{i}")), range(8)))
    assert len(store.list()) == 8


def test_default_url_prefers_the_environment_variable(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///custom.db")
    assert default_url(load_env=False) == "sqlite:///custom.db"


def test_default_url_falls_back_to_a_local_sqlite_file(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    url = default_url(load_env=False)
    assert url.startswith("sqlite:///") and url.endswith("data/calls.db")


def test_safe_url_hides_the_password(tmp_path):
    s = Store(f"sqlite:///{(tmp_path / 'x.db').as_posix()}")
    assert "x.db" in s.safe_url
    s.close()
    from sqlalchemy.engine import make_url
    assert "secret" not in make_url("postgresql://u:secret@h/db").render_as_string(hide_password=True)


def test_cli_save_flag_stores_results(tmp_path, monkeypatch, capsys):
    shutil.copy(CLEAN, tmp_path / "a_clean.txt")
    shutil.copy(BAD, tmp_path / "b_bad.txt")
    db = tmp_path / "cli.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db.as_posix()}")
    assert main([str(tmp_path), "--no-llm", "--save"]) == 0
    assert "Saved 2 result(s)" in capsys.readouterr().out
    check = Store(f"sqlite:///{db.as_posix()}")
    assert {r["call_id"] for r in check.list()} == {"a_clean", "b_bad"}
    check.close()