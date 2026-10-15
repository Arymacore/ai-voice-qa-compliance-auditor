"""
detector.py

Compliance detection. Takes a transcript and checks it against the rule set in
rules.py, returning a structured ComplianceReport.

Two engines:
  - regex (default): fast, free, offline. Matches exact phrases.
  - hybrid (use_llm=True): regex plus an LLM judgment layer (llm_classifier.py).
    If the LLM is unavailable, it falls back to regex and says so in the report.

How hybrid combines the two:
  - Required rules: PASS if regex found the phrase OR the LLM found it in other
    words (and its quote checks out). Regex hits are exact text, so they stand.
  - Prohibited rules: if the LLM gave a usable answer, it decides (it can tell a
    polite question from a demand). Otherwise regex decides.

Usage:
    from src.detection.detector import analyze_file
    report = analyze_file("data/sample/call_002_noncompliant.txt", use_llm=True)

CLI:
    python -m src.detection.detector <file> [--llm]
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from src.detection.llm_classifier import LLMClassificationError, classify_with_llm
from src.detection.rules import ALL_RULES, Rule

SEVERITY_WEIGHTS = {"high": 3, "medium": 2, "low": 1}


@dataclass
class RuleResult:
    rule_id: str
    name: str
    rule_type: str
    severity: str
    passed: bool
    evidence: str | None = None  # the matched text (found phrase or violation)
    source: str = "regex"  # which engine decided: "regex" or "llm"


@dataclass
class ComplianceReport:
    source_file: str
    results: list[RuleResult] = field(default_factory=list)
    engine: str = "regex"  # "regex", "hybrid", or "regex (LLM unavailable)"
    llm_error: str | None = None

    @property
    def failures(self) -> list[RuleResult]:
        return [r for r in self.results if not r.passed]

    @property
    def score(self) -> int:
        """Severity-weighted percentage of rules passed (0-100)."""
        total = sum(SEVERITY_WEIGHTS[r.severity] for r in self.results)
        if total == 0:
            return 100
        earned = sum(SEVERITY_WEIGHTS[r.severity] for r in self.results if r.passed)
        return round(100 * earned / total)

    @property
    def status(self) -> str:
        """PASS = all rules met; FAIL = a high-severity rule failed; REVIEW = minor failures only."""
        if not self.failures:
            return "PASS"
        if any(r.severity == "high" for r in self.failures):
            return "FAIL"
        return "REVIEW"


def extract_agent_text(transcript: str) -> str:
    """
    Return only what the agent said (lines starting 'Agent:').

    Compliance rules apply to the agent, not the customer. If the transcript
    has no speaker labels (e.g., raw Whisper output), fall back to the whole
    text, since we can't tell who said what.
    """
    agent_lines = [
        line.split(":", 1)[1].strip()
        for line in transcript.splitlines()
        if line.strip().lower().startswith("agent:")
    ]
    return " ".join(agent_lines) if agent_lines else transcript


def _first_match(rule: Rule, text: str) -> str | None:
    for pattern in rule.patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(0)
    return None


def analyze_transcript(
    transcript: str,
    source_file: str = "",
    use_llm: bool = False,
    llm_client=None,
) -> ComplianceReport:
    """Check one transcript against every rule and return a ComplianceReport."""
    agent_text = extract_agent_text(transcript)
    report = ComplianceReport(source_file=source_file)

    verdicts = {}
    if use_llm:
        try:
            verdicts = classify_with_llm(agent_text, ALL_RULES, client=llm_client)
            report.engine = "hybrid"
        except LLMClassificationError as exc:
            report.engine = "regex (LLM unavailable)"
            report.llm_error = str(exc)

    for rule in ALL_RULES:
        matched = _first_match(rule, agent_text)
        verdict = verdicts.get(rule.rule_id)
        source = "regex"

        if rule.rule_type == "required":
            passed = matched is not None  # said it = good
            evidence = matched
            if not passed and verdict and verdict.satisfied and verdict.grounded:
                passed, evidence, source = True, verdict.evidence, "llm"
        else:
            if verdict is not None and verdict.grounded:
                passed = verdict.satisfied  # LLM judged the meaning
                evidence = None if passed else verdict.evidence
                source = "llm"
            else:
                passed = matched is None  # said it = violation
                evidence = matched

        report.results.append(
            RuleResult(
                rule_id=rule.rule_id,
                name=rule.name,
                rule_type=rule.rule_type,
                severity=rule.severity,
                passed=passed,
                evidence=evidence,
                source=source,
            )
        )
    return report


def analyze_file(
    file_path: str | Path, use_llm: bool = False, llm_client=None
) -> ComplianceReport:
    """Ingest a call file (Sprint 1 pipeline), then analyze its transcript."""
    from src.ingestion.pipeline import ingest_call

    result = ingest_call(file_path)
    return analyze_transcript(
        result.text, source_file=result.source_file, use_llm=use_llm, llm_client=llm_client
    )


def format_report(report: ComplianceReport) -> str:
    lines = [
        f"File:   {report.source_file}",
        f"Engine: {report.engine}",
        f"Status: {report.status}   Score: {report.score}/100",
        "-" * 60,
    ]
    if report.llm_error:
        lines.insert(2, f"Note:   {report.llm_error}")
    for r in report.results:
        mark = "OK  " if r.passed else "FAIL"
        if r.rule_type == "required":
            detail = f'said: "{r.evidence}"' if r.passed else "never said"
        else:
            detail = "not detected" if r.passed else f'violation: "{r.evidence}"'
        lines.append(f"[{mark}] {r.rule_id} {r.name} ({r.severity}) - {detail} [{r.source}]")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    args = [a for a in sys.argv[1:] if a != "--llm"]
    if len(args) != 1:
        print("Usage: python -m src.detection.detector <path-to-call-file> [--llm]")
        raise SystemExit(1)
    print(format_report(analyze_file(args[0], use_llm="--llm" in sys.argv)))