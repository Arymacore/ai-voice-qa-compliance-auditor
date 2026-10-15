"""
test_detection.py

Tests for the Sprint 2 rule-based detection engine.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.detection.detector import analyze_file, analyze_transcript, extract_agent_text

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "sample"

FULL_DISCLOSURES = (
    "Agent: This call may be recorded for quality assurance. "
    "My name is Sam. This is an attempt to collect a debt. "
    "You have the right to dispute this debt within 30 days."
)


def _result(report, rule_id):
    return next(r for r in report.results if r.rule_id == rule_id)


def test_compliant_call_passes():
    report = analyze_file(SAMPLE_DIR / "call_001_compliant.txt")
    assert report.status == "PASS"
    assert report.score == 100
    assert report.failures == []


def test_noncompliant_call_fails():
    report = analyze_file(SAMPLE_DIR / "call_002_noncompliant.txt")
    assert report.status == "FAIL"
    assert report.score == 0
    assert len(report.failures) == 6


def test_evidence_is_captured_for_violations():
    report = analyze_file(SAMPLE_DIR / "call_002_noncompliant.txt")
    assert "escalate" in _result(report, "P1").evidence.lower()


def test_customer_speech_is_ignored():
    transcript = FULL_DISCLOSURES + "\nCustomer: Fine, I'll pay right now or you will be arrested?"
    report = analyze_transcript(transcript)
    assert _result(report, "P1").passed
    assert _result(report, "P2").passed
    assert report.status == "PASS"


def test_unlabeled_transcript_falls_back_to_full_text():
    text = "You better pay or you will be arrested."
    assert extract_agent_text(text) == text
    assert not _result(analyze_transcript(text), "P1").passed


def test_matching_is_case_insensitive():
    report = analyze_transcript("Agent: THIS CALL MAY BE RECORDED.")
    assert _result(report, "R1").passed


def test_missing_only_minor_rule_is_review():
    transcript = (
        "Agent: This call may be recorded. This is an attempt to collect a debt. "
        "You have the right to dispute this debt."
    )
    report = analyze_transcript(transcript)
    assert _result(report, "R4").passed is False  # no agent name given
    assert report.status == "REVIEW"
    assert 0 < report.score < 100