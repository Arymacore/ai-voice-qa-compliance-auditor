"""
test_analysis.py

Tests for the combined analysis (compliance + tone) and its JSON contract,
using a FAKE client so they run offline and deterministically.
"""

import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.detection.rules import ALL_RULES
from src.detection.tone import DIMENSIONS
from src.ingestion.pipeline import IngestionError
from src.scoring.analysis import analyze_call, analyze_folder, main, summarize

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "sample"
CLEAN = SAMPLE_DIR / "call_001_compliant.txt"
BAD = SAMPLE_DIR / "call_002_noncompliant.txt"
CLEAN_QUOTE = "this call may be recorded for quality assurance purposes"


def compliance_reply():
    results = {r.rule_id: {"satisfied": True, "evidence": None} for r in ALL_RULES}
    return json.dumps({"results": results})


def tone_reply(**overrides):
    body = {d: {"score": 4, "evidence": CLEAN_QUOTE} for d in DIMENSIONS}
    for dim, (score, evidence) in overrides.items():
        body[dim] = {"score": score, "evidence": evidence}
    return json.dumps({"ratings": body})


def routing_client(tone_content=None, error=None):
    """Answers the compliance request and the tone request differently, like the real API."""

    class Completions:
        calls = 0

        def create(self, **kwargs):
            Completions.calls += 1
            if error:
                raise error
            user = kwargs["messages"][1]["content"]
            content = compliance_reply() if user.startswith("RULES:") else (tone_content or tone_reply())
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    return SimpleNamespace(chat=SimpleNamespace(completions=Completions())), Completions


def test_clean_call_produces_the_full_contract():
    client, _ = routing_client()
    r = analyze_call(CLEAN, llm_client=client)
    assert r["schema_version"] == 1
    assert r["call_id"] == "call_001_compliant"
    assert r["source_file"].endswith("call_001_compliant.txt") and "\\" not in r["source_file"]
    assert r["compliance"]["status"] == "PASS" and r["compliance"]["engine"] == "hybrid"
    assert r["tone"]["available"] and r["tone"]["flag"] == "OK"
    assert len(r["compliance"]["rules"]) == len(ALL_RULES)
    assert {x["dimension"] for x in r["tone"]["ratings"]} == set(DIMENSIONS)
    assert r["needs_review"] is False and r["review_reasons"] == []
    assert "Agent:" in r["transcript"]
    assert r["analyzed_at"].endswith("+00:00")
    json.dumps(r)  # must be JSON-serializable


def test_bad_call_and_low_tone_both_appear_as_review_reasons():
    bad_quote = "You need to pay this today or we're going to escalate this"
    client, _ = routing_client(tone_content=tone_reply(professionalism=(2, bad_quote)))
    r = analyze_call(BAD, llm_client=client)
    assert r["compliance"]["status"] == "FAIL"
    assert r["tone"]["flag"] == "REVIEW"
    assert r["needs_review"] is True
    assert r["review_reasons"] == ["compliance FAIL", "tone REVIEW"]


def test_no_llm_mode_uses_regex_only_and_makes_no_requests():
    client, completions = routing_client()
    r = analyze_call(CLEAN, use_llm=False, llm_client=client)
    assert completions.calls == 0
    assert r["compliance"]["engine"] == "regex"
    assert r["tone"]["available"] is False and r["tone"]["score"] is None
    assert r["compliance"]["status"] == "PASS" and r["needs_review"] is False
    json.dumps(r)


def test_transcript_can_be_left_out():
    r = analyze_call(CLEAN, use_llm=False, include_transcript=False)
    assert r["transcript"] is None


def test_api_outage_still_returns_a_result_and_unavailable_tone_does_not_flag():
    client, _ = routing_client(error=RuntimeError("rate limited"))
    r = analyze_call(CLEAN, llm_client=client)
    assert r["compliance"]["engine"] == "regex (LLM unavailable)"
    assert "rate limited" in r["compliance"]["llm_error"]
    assert r["tone"]["available"] is False
    assert r["needs_review"] is False  # outage alone is not a reason to flag a call


def test_unreadable_single_file_raises():
    with pytest.raises(IngestionError):
        analyze_call(SAMPLE_DIR / "nope.txt", use_llm=False)


def test_folder_batch_keeps_going_past_a_bad_file(tmp_path):
    shutil.copy(CLEAN, tmp_path / "a_clean.txt")
    shutil.copy(BAD, tmp_path / "b_bad.txt")
    (tmp_path / "c_empty.txt").write_text("")
    (tmp_path / "ignore_me.pdf").write_text("not a call")
    results = analyze_folder(tmp_path, use_llm=False)
    assert [r["call_id"] for r in results] == ["a_clean", "b_bad", "c_empty"]
    assert "error" in results[2] and "empty" in results[2]["error"]
    assert results[2]["schema_version"] == 1
    json.dumps(results)


def test_summarize_counts_statuses_errors_and_reviews(tmp_path):
    shutil.copy(CLEAN, tmp_path / "a_clean.txt")
    shutil.copy(BAD, tmp_path / "b_bad.txt")
    (tmp_path / "c_empty.txt").write_text("")
    s = summarize(analyze_folder(tmp_path, use_llm=False))
    assert s["total"] == 3 and s["analyzed"] == 2 and s["errors"] == 1
    assert s["by_status"] == {"PASS": 1, "REVIEW": 0, "FAIL": 1}
    assert s["needs_review"] == 1


def test_folder_that_does_not_exist_raises(tmp_path):
    with pytest.raises(NotADirectoryError):
        analyze_folder(tmp_path / "missing")


def test_cli_writes_json_and_prints_summary(tmp_path, capsys):
    shutil.copy(CLEAN, tmp_path / "a_clean.txt")
    shutil.copy(BAD, tmp_path / "b_bad.txt")
    out = tmp_path / "results.json"
    code = main([str(tmp_path), "--no-llm", "--out", str(out)])
    printed = capsys.readouterr().out
    assert code == 0
    assert "2/2 analyzed" in printed and "1 need review" in printed
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert [r["call_id"] for r in saved] == ["a_clean", "b_bad"]


def test_cli_reports_unreadable_single_file(capsys):
    assert main([str(SAMPLE_DIR / "nope.txt"), "--no-llm"]) == 1
    assert "Could not analyze" in capsys.readouterr().out