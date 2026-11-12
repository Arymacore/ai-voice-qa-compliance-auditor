"""
tone_accuracy.py

Scores the model's tone flags against a human answer key.

    python -m src.scoring.tone_accuracy data/tone_labels.csv results.json

The answer key has two columns, call_id and tone_label (OK or REVIEW). The
results file comes from: python -m src.scoring.analysis data/sample --out results.json
REVIEW is treated as the "positive" class (a tone concern).
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

VALID = {"OK", "REVIEW"}


def load_labels(path: str | Path) -> dict[str, str]:
    labels: dict[str, str] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            call_id = (row.get("call_id") or "").strip()
            label = (row.get("tone_label") or "").strip().upper()
            if not call_id:
                continue
            if label not in VALID:
                raise ValueError(f"{call_id}: label must be OK or REVIEW, got '{label}'")
            labels[call_id] = label
    return labels


def load_predictions(path: str | Path) -> dict[str, str | None]:
    results = json.loads(Path(path).read_text(encoding="utf-8"))
    predictions: dict[str, str | None] = {}
    for r in results:
        predictions[r["call_id"]] = None if "error" in r else r["tone"]["flag"]
    return predictions


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def score_tone(labels: dict[str, str], predictions: dict[str, str | None]) -> dict:
    """Accuracy, precision and recall. A call with no usable model flag counts as wrong."""
    tp = fp = fn = tn = 0
    mismatches, unscored = [], []
    for call_id, truth in sorted(labels.items()):
        pred = predictions.get(call_id)
        if pred not in VALID:
            unscored.append(call_id)
            continue
        if truth == "REVIEW" and pred == "REVIEW":
            tp += 1
        elif truth == "OK" and pred == "REVIEW":
            fp += 1
            mismatches.append((call_id, truth, pred))
        elif truth == "REVIEW" and pred == "OK":
            fn += 1
            mismatches.append((call_id, truth, pred))
        else:
            tn += 1
    total = len(labels)
    return {
        "total": total,
        "correct": tp + tn,
        "accuracy": _ratio(tp + tn, total),
        "precision": _ratio(tp, tp + fp),
        "recall": _ratio(tp, tp + fn),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "mismatches": mismatches,
        "unscored": unscored,
    }


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.scoring.tone_accuracy")
    parser.add_argument("labels", help="CSV answer key (call_id,tone_label)")
    parser.add_argument("results", help="JSON file from analysis.py --out")
    args = parser.parse_args(argv)

    try:
        labels = load_labels(args.labels)
    except ValueError as exc:
        print(f"Answer key problem: {exc}")
        return 1
    if not labels:
        print("The answer key has no rows.")
        return 1

    s = score_tone(labels, load_predictions(args.results))
    print(f"Tone accuracy: {s['correct']}/{s['total']} = {_pct(s['accuracy'])}")
    print(f"Precision (REVIEW flags that were right): {_pct(s['precision'])}")
    print(f"Recall (real tone problems caught):       {_pct(s['recall'])}")
    print(f"Confusion: TP {s['tp']}, FP {s['fp']}, FN {s['fn']}, TN {s['tn']}")
    for call_id, truth, pred in s["mismatches"]:
        print(f"  MISMATCH {call_id}: you said {truth}, model said {pred}")
    for call_id in s["unscored"]:
        print(f"  NO MODEL FLAG {call_id} (counted as wrong)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
