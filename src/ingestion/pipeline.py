"""
pipeline.py

The single entry point for ingestion: given a raw uploaded file (audio or
text), validate it and return a clean transcript ready for the detection
engine (Sprint 2) to consume.

Usage:
    from src.ingestion.pipeline import ingest_call

    result = ingest_call("data/sample/call_001.txt")
    print(result.text)
"""

from __future__ import annotations

from pathlib import Path

from src.ingestion.file_validator import validate_file
from src.ingestion.transcriber import (
    TranscriptionError,
    TranscriptionResult,
    read_text_transcript,
    transcribe_audio,
)


class IngestionError(Exception):
    """Raised when a file fails validation or transcription during ingestion."""


def ingest_call(file_path: str | Path) -> TranscriptionResult:
    """
    Validate and transcribe a single call file.

    Raises IngestionError with a human-readable message on any failure, so
    calling code (e.g., a future API endpoint) can surface it cleanly.
    """
    validation = validate_file(file_path)
    if not validation.is_valid:
        raise IngestionError(validation.error)

    try:
        if validation.file_type == "audio":
            return transcribe_audio(file_path)
        else:  # "text"
            return read_text_transcript(file_path)
    except TranscriptionError as exc:
        raise IngestionError(str(exc)) from exc


if __name__ == "__main__":
    # Quick manual smoke test: run `python -m src.ingestion.pipeline <file>`
    import sys

    if len(sys.argv) != 2:
        print("Usage: python -m src.ingestion.pipeline <path-to-call-file>")
        raise SystemExit(1)

    try:
        result = ingest_call(sys.argv[1])
        print(f"[{result.provider}] Transcript for {result.source_file}:\n")
        print(result.text)
    except IngestionError as exc:
        print(f"Ingestion failed: {exc}")
        raise SystemExit(1)