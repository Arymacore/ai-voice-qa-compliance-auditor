"""
evaluate.py

Measures how accurate the detector is by comparing its output to the
human-labeled answer key in data/labels.csv.

In labels.csv, 1 = the rule was satisfied (required rule met / prohibited
rule not violated) and 0 = it was missed or violated.

Run from the project root:
    python -m src.detection.evaluate          (regex rules only)
    python -m src.detection.evaluate --llm    (regex + LLM hybrid; needs OPENAI_API_KEY)
"""

from __future__ import annotations

import csv
from pathlib import Path

from src.detection.detector import analyze_file

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DIR = ROOT / "data" / "sample"
LABELS_PATH = ROOT / "data" / "labels.csv"
RULE_IDS = ["R1", "R2", "R3", "R4", "P1", "P2"]


def load_labels(path: Path = LABELS_PATH) -> list[dict]:
    # utf-8-sig quietly handles a BOM if the CSV was saved by Excel/Notepad
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def evaluate(
    labels_path: Path = LABELS_PATH,
    sample_dir: Path = SAMPLE_DIR,
    use_llm: bool = False,
    llm_client=None,
) -> dict:
    """Run the detector on every labeled call and return accuracy stats."""
    rows = load_labels(labels_path)

    rule_total = rule_correct = status_correct = 0
    tp = fp = fn = tn = 0  # "flagged" = status is anything other than PASS
    mismatches: list[dict] = []
    per_call: list[dict] = []
    llm_failures = 0
    llm_error = None

    for row in rows:
        report = analyze_file(sample_dir / row["file"], use_llm=use_llm, llm_client=llm_client)
        if use_llm and report.llm_error:
            llm_failures += 1
            llm_error = llm_error or report.llm_error
        by_id = {r.rule_id: r for r in report.results}

        for rule_id in RULE_IDS:
            expected_pass = row[rule_id] == "1"
            result = by_id[rule_id]
            rule_total += 1
            if expected_pass == result.passed:
                rule_correct += 1
            else:
                mismatches.append(
                    {
                        "file": row["file"],
                        "rule_id": rule_id,
                        "rule_name": result.name,
                        "kind": "FALSE ALARM" if expected_pass else "MISSED",
                        "evidence": result.evidence,
                    }
                )

        status_ok = report.status == row["status"]
        status_correct += status_ok
        should_flag = row["status"] != "PASS"
        did_flag = report.status != "PASS"
        if should_flag and did_flag:
            tp += 1
        elif did_flag:
            fp += 1
        elif should_flag:
            fn += 1
        else:
            tn += 1

        per_call.append(
            {
                "file": row["file"],
                "expected": row["status"],
                "got": report.status,
                "ok": status_ok,
            }
        )

    return {
        "calls": len(rows),
        "status_correct": status_correct,
        "rule_total": rule_total,
        "rule_correct": rule_correct,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "mismatches": mismatches,
        "per_call": per_call,
        "engine": "hybrid (regex + LLM)" if use_llm else "regex only",
        "llm_failures": llm_failures,
        "llm_error": llm_error,
    }


def _pct(num: int, den: int) -> str:
    return f"{num}/{den} ({100 * num / den:.1f}%)" if den else "n/a"


def format_summary(stats: dict) -> str:
    lines = [
        f"Evaluated {stats['calls']} calls against data/labels.csv",
        f"Engine: {stats['engine']}",
        "",
    ]
    if stats["llm_failures"]:
        lines += [
            f"WARNING: the LLM was unavailable for {stats['llm_failures']} call(s), "
            "so those used regex only. These numbers are NOT a real hybrid result.",
            f"         First error: {stats['llm_error']}",
            "",
        ]

    lines.append("PER-CALL RESULTS")
    for c in stats["per_call"]:
        flag = "ok" if c["ok"] else "WRONG"
        lines.append(f"  {c['file']:<42} expected {c['expected']:<7} got {c['got']:<7} {flag}")

    lines += ["", "RULE-LEVEL MISTAKES"]
    if not stats["mismatches"]:
        lines.append("  none")
    for m in stats["mismatches"]:
        if m["kind"] == "FALSE ALARM" and m["evidence"]:
            detail = f'flagged fine behavior, matched: "{m["evidence"]}"'
        elif m["kind"] == "FALSE ALARM":
            detail = "disclosure was given, but wording didn't match any pattern"
        else:
            detail = "real problem went undetected"
        lines.append(f"  {m['file']}  {m['rule_id']} {m['rule_name']}: {m['kind']} - {detail}")

    flagged = stats["tp"] + stats["fp"]
    problems = stats["tp"] + stats["fn"]
    lines += [
        "",
        "SUMMARY",
        f"  Status accuracy:     {_pct(stats['status_correct'], stats['calls'])}",
        f"  Rule-level accuracy: {_pct(stats['rule_correct'], stats['rule_total'])}",
        f"  Flagging precision:  {_pct(stats['tp'], flagged)}  (of calls flagged, how many truly had a problem)",
        f"  Flagging recall:     {_pct(stats['tp'], problems)}  (of calls with a problem, how many we caught)",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    print(format_summary(evaluate(use_llm="--llm" in sys.argv)))