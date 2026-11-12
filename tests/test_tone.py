"""
test_tone.py

Tests for tone scoring using a FAKE client (offline, free, deterministic).
They check our parsing, verification, scoring, and failure handling - not the
model's judgment itself.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.detection.detector import extract_agent_text
from src.detection.llm_classifier import LLMClassificationError
from src.detection.tone import (
    DIMENSIONS,
    analyze_tone,
    build_tone_messages,
    parse_tone_response,
)

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "sample"
HOSTILE = (SAMPLE_DIR / "call_008_hostile_customer.txt").read_text(encoding="utf-8")
AGENT = extract_agent_text(HOSTILE)
QUOTE = "I understand you're upset"


def reply(**ratings):
    """JSON reply: every dimension 4 with a real quote, except overrides {dim: (score, evidence)}."""
    body = {d: {"score": 4, "evidence": QUOTE} for d in DIMENSIONS}
    for dim, (score, evidence) in ratings.items():
        body[dim] = {"score": score, "evidence": evidence}
    return json.dumps({"ratings": body})


def fake_client(content=None, error=None):
    class Completions:
        last_kwargs = None

        def create(self, **kwargs):
            Completions.last_kwargs = kwargs
            if error:
                raise error
            msg = SimpleNamespace(content=content)
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    return SimpleNamespace(chat=SimpleNamespace(completions=Completions())), Completions


def by_dim(report):
    return {r.dimension: r for r in report.ratings}


def test_good_ratings_are_scored_and_flagged_ok():
    r = analyze_tone(HOSTILE, client=fake_client(reply(professionalism=(5, QUOTE), composure=(5, QUOTE), empathy=(3, QUOTE)))[0])
    assert r.available and r.flag == "OK"
    assert r.score == round(100 * ((5 + 5 + 3) / 3 - 1) / 4)


def test_low_rating_with_quote_is_a_concern_and_flags_review():
    r = analyze_tone(HOSTILE, client=fake_client(reply(empathy=(2, QUOTE)))[0])
    assert r.flag == "REVIEW"
    assert [c.dimension for c in r.concerns] == ["empathy"]


def test_absent_quality_can_be_rated_low_without_a_quote():
    r = analyze_tone(HOSTILE, client=fake_client(reply(empathy=(1, None)))[0])
    assert by_dim(r)["empathy"].score == 1


def test_absent_quality_lowers_the_score_but_does_not_flag():
    baseline = analyze_tone(HOSTILE, client=fake_client(reply())[0])
    r = analyze_tone(HOSTILE, client=fake_client(reply(empathy=(1, None)))[0])
    assert r.score < baseline.score  # the missing empathy still costs points
    assert r.concerns == []
    assert r.flag == "OK"  # but nothing the agent said was bad


def test_high_rating_without_a_quote_is_unrated():
    r = analyze_tone(HOSTILE, client=fake_client(reply(empathy=(5, None)))[0])
    assert by_dim(r)["empathy"].score is None
    assert by_dim(r)["empathy"].reason == "no supporting quote"


def test_fabricated_quote_is_unrated():
    r = analyze_tone(HOSTILE, client=fake_client(reply(composure=(5, "a sentence nobody said")))[0])
    assert by_dim(r)["composure"].score is None
    assert "not found" in by_dim(r)["composure"].reason


def test_customers_words_cannot_serve_as_evidence():
    r = analyze_tone(HOSTILE, client=fake_client(reply(composure=(1, "You people are crooks")))[0])
    assert by_dim(r)["composure"].score is None  # that line is the customer's

def test_unlabeled_transcript_returns_unavailable():
    transcript = (
        "Hello, how are you? "
        "Honestly, I didn't realize that I owed that much. "
        "I understand you're upset."
    )

    client, completions = fake_client(reply())

    report = analyze_tone(transcript, client=client)

    assert report.available is False
    assert report.flag == "UNAVAILABLE"
    assert report.score is None
    assert "speaker labels are missing" in report.error.lower()

    # The LLM must not be called when agent speech cannot be identified.
    assert completions.last_kwargs is None


def test_customer_only_labeled_transcript_returns_unavailable():
    transcript = (
        "Customer: I am upset about this account.\n"
        "Customer: I want someone to explain the charges."
    )

    client, completions = fake_client(reply())

    report = analyze_tone(transcript, client=client)

    assert report.available is False
    assert report.flag == "UNAVAILABLE"
    assert report.score is None
    assert completions.last_kwargs is None


def test_agent_labeled_transcript_still_gets_tone_analysis():
    transcript = (
        "Agent: I understand you're upset. "
        "I will do my best to help you."
        "\\nCustomer: Thank you."
    )

    quote = "I understand you're upset"
    client, completions = fake_client(
        reply(
            professionalism=(4, quote),
            empathy=(5, quote),
            composure=(4, quote),
        )
    )

    report = analyze_tone(transcript, client=client)

    assert report.available is True
    assert report.flag == "OK"
    assert report.score is not None
    assert completions.last_kwargs is not None


@pytest.mark.parametrize("bad", [0, 6, "4", 3.5, True, None])
def test_invalid_scores_are_unrated(bad):
    content = json.dumps({"ratings": {d: {"score": 4, "evidence": QUOTE} for d in DIMENSIONS}
                          | {"empathy": {"score": bad, "evidence": QUOTE}}})
    r = analyze_tone(HOSTILE, client=fake_client(content)[0])
    assert by_dim(r)["empathy"].score is None


def test_missing_dimension_is_unrated():
    body = {d: {"score": 4, "evidence": QUOTE} for d in list(DIMENSIONS)[:2]}
    r = analyze_tone(HOSTILE, client=fake_client(json.dumps({"ratings": body}))[0])
    assert by_dim(r)["composure"].score is None


def test_non_json_reply_is_reported_unavailable_not_raised():
    r = analyze_tone(HOSTILE, client=fake_client("definitely not json")[0])
    assert not r.available and r.flag == "UNAVAILABLE" and r.score is None


def test_parse_raises_on_non_json():
    with pytest.raises(LLMClassificationError):
        parse_tone_response("nope", AGENT)


def test_api_failure_is_reported_unavailable():
    r = analyze_tone(HOSTILE, client=fake_client(error=RuntimeError("rate limited"))[0])
    assert not r.available and "rate limited" in r.error


def test_everything_unrated_is_unavailable_flag():
    content = json.dumps({"ratings": {}})
    r = analyze_tone(HOSTILE, client=fake_client(content)[0])
    assert r.available and r.flag == "UNAVAILABLE"


def test_request_includes_customer_context_marks_data_untrusted_and_uses_json_mode():
    client, completions = fake_client(reply())
    analyze_tone(HOSTILE, client=client)
    sent = completions.last_kwargs
    assert "crooks" in sent["messages"][1]["content"]  # customer context is sent
    assert "untrusted" in build_tone_messages("x")[0]["content"].lower()
    assert sent["response_format"] == {"type": "json_object"}
    assert sent["temperature"] == 0