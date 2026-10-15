"""
test_evaluation.py

Guards the detector's accuracy so a change to the rules (or a future LLM
layer) can't quietly make it worse.

BASELINE_* are the Sprint 2 rule-based results on our 10 labeled calls.
When detection genuinely improves, raise these numbers.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.detection.evaluate import SAMPLE_DIR, evaluate, load_labels

# Lowered after adding calls 011-014 (paraphrased and implied cases that regex
# handles poorly by design). The hybrid engine is what closes this gap.
BASELINE_STATUS_ACCURACY = 0.64
BASELINE_RULE_ACCURACY = 0.86


def test_every_sample_call_has_a_label():
    labeled = {row["file"] for row in load_labels()}
    on_disk = {p.name for p in SAMPLE_DIR.glob("*.txt")}
    assert on_disk == labeled


def test_status_accuracy_meets_baseline():
    stats = evaluate()
    assert stats["status_correct"] / stats["calls"] >= BASELINE_STATUS_ACCURACY


def test_rule_accuracy_meets_baseline():
    stats = evaluate()
    assert stats["rule_correct"] / stats["rule_total"] >= BASELINE_RULE_ACCURACY