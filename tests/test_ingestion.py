"""
test_ingestion.py

Basic tests for the Sprint 1 ingestion pipeline. Covers the text-transcript
path fully (no API key needed). The audio path isn't unit-tested here since
calling the real Whisper API requires a paid key and network access a test
suite shouldn't depend on.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ingestion.file_validator import validate_file, MAX_FILE_SIZE_BYTES
from src.ingestion.pipeline import ingest_call, IngestionError

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "sample"


def test_validate_existing_text_file():
    result = validate_file(SAMPLE_DIR / "call_001_compliant.txt")
    assert result.is_valid
    assert result.file_type == "text"


def test_validate_missing_file():
    result = validate_file(SAMPLE_DIR / "does_not_exist.txt")
    assert not result.is_valid
    assert "does not exist" in result.error


def test_validate_unsupported_extension(tmp_path):
    bad_file = tmp_path / "call.pdf"
    bad_file.write_text("not a real transcript")
    result = validate_file(bad_file)
    assert not result.is_valid
    assert "Unsupported file type" in result.error


def test_validate_empty_file(tmp_path):
    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("")
    result = validate_file(empty_file)
    assert not result.is_valid
    assert "empty" in result.error


def test_validate_oversized_file(tmp_path):
    big_file = tmp_path / "big.txt"
    big_file.write_bytes(b"a" * (MAX_FILE_SIZE_BYTES + 1))
    result = validate_file(big_file)
    assert not result.is_valid
    assert "size limit" in result.error


def test_ingest_text_transcript_end_to_end():
    result = ingest_call(SAMPLE_DIR / "call_001_compliant.txt")
    assert result.provider == "pre-transcribed"
    assert "debt collector" in result.text
    assert len(result.text) > 0


def test_ingest_raises_on_missing_file():
    with pytest.raises(IngestionError):
        ingest_call(SAMPLE_DIR / "nope.txt")