"""
analysis.py

Combines everything we know about one call - compliance and tone - into a
single JSON-ready dict (the "analysis contract") that the API and dashboard
consume, plus a batch mode for a whole folder.

Contract for one analyzed call (schema_version 1):
    {
      "schema_version": 1,
      "call_id": "call_001_compliant",
      "source_file": "data/sample/call_001_compliant.txt",
      "analyzed_at": "2026-10-27T15:04:05+00:00",
      "needs_review": false,
      "review_reasons": [],                      # e.g. ["compliance FAIL", "tone REVIEW"]
      "compliance": {"status", "score", "engine", "llm_error", "rules": [...]},
      "tone": {"available", "flag", "score", "error", "ratings": [...]},
      "transcript": "..." or null
    }
A call that could not be read is reported as
    {"schema_version": 1, "call_id", "source_file", "error": "..."}
so one bad file never stops a batch. Consumers must check for the "error" key.

Tone never affects compliance status: needs_review is true when compliance is
not PASS or tone is REVIEW; an unavailable tone result alone does not flag a call.

CLI:
    python -m src.scoring.analysis <file-or-folder> [--no-llm] [--out results.json] [--save]
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from src.detection.detector import ComplianceReport, analyze_transcript
from src.detection.tone import ToneReport, analyze_tone
from src.ingestion.file_validator import (
    SUPPORTED_AUDIO_EXTENSIONS,
    SUPPORTED_TEXT_EXTENSIONS,
)
from src.ingestion.pipeline import IngestionError, ingest_call

SCHEMA_VERSION = 1

# One headline number per call: compliance counts for most of it, tone for the rest.
COMPLIANCE_WEIGHT = 0.7
TONE_WEIGHT = 0.3


def combined_score(compliance_score: int, tone_score: int | None) -> int:
    """Weighted blend of compliance and tone (0-100). Compliance alone if tone is unavailable."""
    if tone_score is None:
        return int(compliance_score)
    return round(COMPLIANCE_WEIGHT * compliance_score + TONE_WEIGHT * tone_score)


def compliance_to_dict(report: ComplianceReport) -> dict:
    return {
        "status": report.status,
        "score": report.score,
        "engine": report.engine,
        "llm_error": report.llm_error,
        "rules": [
            {
                "rule_id": r.rule_id,
                "name": r.name,
                "type": r.rule_type,
                "severity": r.severity,
                "passed": r.passed,
                "evidence": r.evidence,
                "source": r.source,
            }
            for r in report.results
        ],
    }


def tone_to_dict(report: ToneReport) -> dict:
    return {
        "available": report.available,
        "flag": report.flag,
        "score": report.score,
        "error": report.error,
        "ratings": [
            {
                "dimension": r.dimension,
                "score": r.score,
                "evidence": r.evidence,
                "reason": r.reason,
            }
            for r in report.ratings
        ],
    }


def analyze_call(
    file_path: str | Path,
    use_llm: bool = True,
    llm_client=None,
    include_transcript: bool = True,
) -> dict:
    """Ingest one call and return its full analysis. Raises IngestionError if unreadable."""
    ingested = ingest_call(file_path)
    text = ingested.text

    compliance = analyze_transcript(
        text, source_file=ingested.source_file, use_llm=use_llm, llm_client=llm_client
    )
    if use_llm:
        tone = analyze_tone(text, client=llm_client)
    else:
        tone = ToneReport(available=False, error="Tone scoring is off (LLM disabled).")

    reasons = []
    if compliance.status != "PASS":
        reasons.append(f"compliance {compliance.status}")
    if tone.flag == "REVIEW":
        reasons.append("tone REVIEW")

    return {
        "schema_version": SCHEMA_VERSION,
        "call_id": Path(file_path).stem,
        "source_file": Path(ingested.source_file).as_posix(),
        "analyzed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "needs_review": bool(reasons),
        "combined_score": combined_score(compliance.score, tone.score),
        "review_reasons": reasons,
        "compliance": compliance_to_dict(compliance),
        "tone": tone_to_dict(tone),
        "transcript": text if include_transcript else None,
    }


def analyze_folder(
    folder: str | Path,
    use_llm: bool = True,
    llm_client=None,
    include_transcript: bool = True,
) -> list[dict]:
    """Analyze every supported call file in a folder (sorted by name)."""
    folder = Path(folder)
    if not folder.is_dir():
        raise NotADirectoryError(f"{folder} is not a folder.")
    supported = SUPPORTED_AUDIO_EXTENSIONS | SUPPORTED_TEXT_EXTENSIONS

    results = []
    for path in sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in supported):
        try:
            results.append(analyze_call(path, use_llm, llm_client, include_transcript))
        except IngestionError as exc:
            results.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "call_id": path.stem,
                    "source_file": path.as_posix(),
                    "error": str(exc),
                }
            )
    return results


def summarize(results: list[dict]) -> dict:
    """Headline numbers for a dashboard header."""
    analyzed = [r for r in results if "error" not in r]
    by_status = {"PASS": 0, "REVIEW": 0, "FAIL": 0}
    for r in analyzed:
        by_status[r["compliance"]["status"]] += 1
    return {
        "total": len(results),
        "analyzed": len(analyzed),
        "errors": len(results) - len(analyzed),
        "by_status": by_status,
        "needs_review": sum(r["needs_review"] for r in analyzed),
        "tone_review": sum(r["tone"]["flag"] == "REVIEW" for r in analyzed),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.scoring.analysis",
        description="Analyze one call file or a whole folder (compliance + tone).",
    )
    parser.add_argument("path", help="a call file or a folder of call files")
    parser.add_argument("--no-llm", action="store_true", help="regex only; skips tone scoring")
    parser.add_argument("--out", help="write the full JSON results to this file")
    parser.add_argument("--save", action="store_true", help="store results in the database (DATABASE_URL)")
    args = parser.parse_args(argv)

    target = Path(args.path)
    use_llm = not args.no_llm
    try:
        if target.is_dir():
            results = analyze_folder(target, use_llm=use_llm)
        else:
            results = [analyze_call(target, use_llm=use_llm)]
    except IngestionError as exc:
        print(f"Could not analyze {target}: {exc}")
        return 1

    for r in results:
        if "error" in r:
            print(f"{r['call_id']:<42} ERROR: {r['error']}")
            continue
        flag = "  <- needs review" if r["needs_review"] else ""
        print(
            f"{r['call_id']:<42} compliance {r['compliance']['status']:<7} "
            f"tone {r['tone']['flag']:<12}{flag}"
        )

    s = summarize(results)
    print(
        f"\n{s['analyzed']}/{s['total']} analyzed ({s['errors']} errors) | "
        f"PASS {s['by_status']['PASS']}, REVIEW {s['by_status']['REVIEW']}, FAIL {s['by_status']['FAIL']} | "
        f"{s['needs_review']} need review"
    )

    if args.save:
        from src.storage import Store

        store = Store()
        store.save_many(results)
        print(f"Saved {len(results)} result(s) to {store.safe_url}")
        store.close()

    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Full results written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())