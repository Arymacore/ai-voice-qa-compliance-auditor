"""
test_llm.py

Tests for the LLM layer using a FAKE client, so they run offline, free, and
deterministically. They check OUR logic (parsing, grounding, how regex and LLM
are combined, fallback), not the model's intelligence - that is what
`python -m src.detection.evaluate --llm` measures with the real API.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.detection.detector import analyze_transcript
from src.detection.evaluate import evaluate
from src.detection.llm_classifier import (
    LLMClassificationError,
    build_messages,
    parse_response,
)
from src.detection.rules import ALL_RULES

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "sample"
RULE_IDS = [r.rule_id for r in ALL_RULES]


def read(name):
    return (SAMPLE_DIR / name).read_text(encoding="utf-8")


def payload(**overrides):
    """JSON reply where every rule is satisfied, except the overrides {rule_id: (satisfied, evidence)}."""
    results = {rid: {"satisfied": True, "evidence": None} for rid in RULE_IDS}
    for rid, (satisfied, evidence) in overrides.items():
        results[rid] = {"satisfied": satisfied, "evidence": evidence}
    return json.dumps({"results": results})


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


def result(report, rule_id):
    return next(r for r in report.results if r.rule_id == rule_id)


# ---------- parsing and grounding ----------

def test_parse_valid_response():
    verdicts = parse_response(payload(), "anything", ALL_RULES)
    assert set(verdicts) == set(RULE_IDS)


def test_parse_rejects_non_json():
    with pytest.raises(LLMClassificationError):
        parse_response("not json at all", "text", ALL_RULES)


def test_quote_not_in_transcript_is_ungrounded():
    reply = payload(R1=(True, "we definitely recorded this"))
    verdicts = parse_response(reply, "Hello, how are you today?", ALL_RULES)
    assert verdicts["R1"].grounded is False


def test_quote_with_ellipsis_is_grounded_if_each_part_matches():
    reply = payload(R1=(True, "we record ... these calls"))
    text = "Just so you know, we record all of these calls."
    assert parse_response(reply, text, ALL_RULES)["R1"].grounded is True


def test_entry_with_wrong_type_is_skipped():
    reply = json.dumps({"results": {"R1": {"satisfied": "yes", "evidence": None}}})
    assert "R1" not in parse_response(reply, "text", ALL_RULES)


# ---------- what is sent to the model ----------

def test_only_agent_speech_is_sent_and_json_mode_is_used():
    text = read("call_008_hostile_customer.txt")
    client, completions = fake_client(content=payload())
    analyze_transcript(text, use_llm=True, llm_client=client)
    sent = completions.last_kwargs
    user_message = sent["messages"][1]["content"]
    assert "you will be arrested" not in user_message  # customer's words stay out
    assert "may be recorded" in user_message  # agent's words go in
    assert sent["response_format"] == {"type": "json_object"}
    assert sent["temperature"] == 0


def test_prompt_marks_call_text_as_untrusted():
    system = build_messages("x", ALL_RULES)[0]["content"]
    assert "untrusted" in system.lower()


# ---------- how regex and LLM combine ----------

def test_llm_rescues_paraphrased_disclosures():
    text = read("call_009_paraphrased_compliant.txt")
    reply = payload(
        R1=(True, "we record these calls"),
        R2=(True, "I'm a debt collector"),
        R4=(True, "I'm Priya"),
    )
    client, _ = fake_client(content=reply)
    report = analyze_transcript(text, use_llm=True, llm_client=client)
    assert report.engine == "hybrid"
    assert report.status == "PASS"
    assert result(report, "R1").source == "llm"


def test_llm_catches_implied_threat_regex_missed():
    text = read("call_007_implied_threat.txt")
    quote = "I'll make sure your employer and your neighbors hear all about this"
    client, _ = fake_client(content=payload(P1=(False, quote)))
    report = analyze_transcript(text, use_llm=True, llm_client=client)
    assert not result(report, "P1").passed
    assert report.status == "FAIL"


def test_llm_overrides_regex_false_alarm_on_polite_question():
    text = read("call_010_polite_payment_ask.txt")
    assert analyze_transcript(text).status == "REVIEW"  # regex alone is fooled
    client, _ = fake_client(content=payload())  # LLM: no violation
    report = analyze_transcript(text, use_llm=True, llm_client=client)
    assert result(report, "P2").passed
    assert report.status == "PASS"


def test_ungrounded_violation_claim_falls_back_to_regex():
    text = read("call_006_explicit_threat.txt")
    client, _ = fake_client(content=payload(P1=(False, "a quote the agent never said")))
    report = analyze_transcript(text, use_llm=True, llm_client=client)
    assert not result(report, "P1").passed  # regex still catches "we will sue you"
    assert result(report, "P1").source == "regex"


def test_llm_cannot_erase_a_regex_confirmed_disclosure():
    text = read("call_001_compliant.txt")
    reply = payload(R1=(False, None))  # LLM wrongly says "not said"
    client, _ = fake_client(content=reply)
    report = analyze_transcript(text, use_llm=True, llm_client=client)
    assert result(report, "R1").passed  # exact phrase "may be recorded" stands


# ---------- failure handling ----------

def test_api_failure_falls_back_to_regex_with_note():
    text = read("call_002_noncompliant.txt")
    client, _ = fake_client(error=RuntimeError("rate limited"))
    report = analyze_transcript(text, use_llm=True, llm_client=client)
    assert report.engine == "regex (LLM unavailable)"
    assert "rate limited" in report.llm_error
    assert report.status == "FAIL"  # regex result still produced


def test_evaluate_warns_when_llm_unavailable():
    client, _ = fake_client(error=RuntimeError("no key"))
    stats = evaluate(use_llm=True, llm_client=client)
    assert stats["llm_failures"] == stats["calls"]
    assert stats["status_correct"] == 9  # identical to the regex baseline