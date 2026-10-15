"""
transcriber.py

Wraps an ASR (automatic speech recognition) provider so the rest of the
pipeline never has to know which transcription service is behind it.

For Sprint 1, this targets the OpenAI Whisper API. If the provider changes
later, only this file should need to change — everything downstream just
calls `transcribe_audio()` or `read_text_transcript()`.

Requires:
    pip install openai   (already done in Step 4)

Environment variable required:
    OPENAI_API_KEY   (never hardcode this — see docs/security.md)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - dependency not installed yet
    OpenAI = None  # type: ignore


class TranscriptionError(Exception):
    """Raised when a file cannot be transcribed."""


@dataclass
class TranscriptionResult:
    text: str
    source_file: str
    provider: str = "whisper-1"


def _get_client() -> "OpenAI":
    if OpenAI is None:
        raise TranscriptionError(
            "The 'openai' package is not installed. Run: pip install openai"
        )
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise TranscriptionError(
            "OPENAI_API_KEY is not set. Add it to your environment (see .env.example)."
        )
    return OpenAI(api_key=api_key)


def transcribe_audio(file_path: str | Path) -> TranscriptionResult:
    """
    Transcribe a single audio file using the Whisper API.

    This is the audio path of ingestion. For plain-text transcripts (already
    in text form), use `read_text_transcript` instead — no API call needed.
    """
    path = Path(file_path)
    client = _get_client()

    with open(path, "rb") as audio_file:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
        )

    return TranscriptionResult(text=response.text, source_file=str(path))


def read_text_transcript(file_path: str | Path) -> TranscriptionResult:
    """
    Read an already-transcribed call (plain .txt file) without calling any API.
    Used for calls sourced from public transcript datasets rather than raw audio.
    """
    path = Path(file_path)
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise TranscriptionError(f"Text transcript at {path} is empty.")
    return TranscriptionResult(text=text, source_file=str(path), provider="pre-transcribed")