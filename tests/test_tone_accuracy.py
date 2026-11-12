"""Tests for the tone accuracy scorer."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.scoring.tone_accuracy import load_labels, load_predictions, main, score_tone


def test_perfect_match():
    labels = {"a": "OK", "b": "REVIEW"}
    s = score_tone(labels, {"a": "OK", "b": "REVIEW"})
    assert s["accuracy"] == 1.0 and s["precision"] == 1.0 and s["recall"] == 1.0
    assert s["mismatches"] == []


def test_false_positive_and_false_negative():
    labels = {"a": "OK", "b": "REVIEW", "c": "REVIEW", "d": "OK"}
    preds = {"a": "REVIEW", "b": "OK", "c": "REVIEW", "d": "OK"}
    s = score_tone(labels, preds)
    assert (s["tp"], s["fp"], s["fn"], s["tn"]) == (1, 1, 1, 1)
    assert s["accuracy"] == 0.5 and s["precision"] == 0.5 and s["recall"] == 0.5
    assert {m[0] for m in s["mismatches"]} == {"a", "b"}


def test_missing_or_unusable_flag_counts_as_wrong():
    s = score_tone({"a": "OK", "b": "OK"}, {"a": "OK", "b": None})
    assert s["accuracy"] == 0.5
    assert s["unscored"] == ["b"]


def test_blank_label_is_rejected(tmp_path):
    f = tmp_path / "labels.csv"
    f.write_text("call_id,tone_label\ncall_1,\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_labels(f)


def test_cli_end_to_end(tmp_path, capsys):
    labels = tmp_path / "labels.csv"
    labels.write_text("call_id,tone_label\ncall_1,OK\ncall_2,REVIEW\n", encoding="utf-8")
    results = tmp_path / "results.json"
    results.write_text(json.dumps([
        {"call_id": "call_1", "tone": {"flag": "OK"}},
        {"call_id": "call_2", "tone": {"flag": "REVIEW"}},
        {"call_id": "call_3", "error": "unreadable"},
    ]), encoding="utf-8")
    assert load_predictions(results)["call_3"] is None
    assert main([str(labels), str(results)]) == 0
    assert "2/2 = 100.0%" in capsys.readouterr().out
