"""
file_validator.py

Validates uploaded call files (audio or plain-text transcripts) before they
enter the ingestion pipeline. Keeps bad/oversized/unsupported files out early,
which is both a data-quality and a basic security control (see docs/security.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Supported input types for Sprint 1. Extend this set as new formats are validated.
SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a"}
SUPPORTED_TEXT_EXTENSIONS = {".txt"}

# Keep uploads small for the MVP — a single call is rarely more than a few MB
# as compressed audio or a few KB as text. 25 MB is a generous ceiling.
MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024


@dataclass
class ValidationResult:
    is_valid: bool
    file_type: str | None  # "audio" | "text" | None
    error: str | None = None


def validate_file(file_path: str | Path) -> ValidationResult:
    """
    Validate a single uploaded file for the ingestion pipeline.

    Checks:
      1. The file exists.
      2. The file extension is a supported audio or text type.
      3. The file size is within the allowed limit.

    Returns a ValidationResult rather than raising, so callers (e.g., an API
    endpoint) can turn this into a clean 4xx response instead of a 500.
    """
    path = Path(file_path)

    if not path.exists() or not path.is_file():
        return ValidationResult(is_valid=False, file_type=None, error="File does not exist.")

    extension = path.suffix.lower()

    if extension in SUPPORTED_AUDIO_EXTENSIONS:
        file_type = "audio"
    elif extension in SUPPORTED_TEXT_EXTENSIONS:
        file_type = "text"
    else:
        supported = SUPPORTED_AUDIO_EXTENSIONS | SUPPORTED_TEXT_EXTENSIONS
        return ValidationResult(
            is_valid=False,
            file_type=None,
            error=f"Unsupported file type '{extension}'. Supported types: {sorted(supported)}",
        )

    size = path.stat().st_size
    if size == 0:
        return ValidationResult(is_valid=False, file_type=file_type, error="File is empty.")
    if size > MAX_FILE_SIZE_BYTES:
        mb = MAX_FILE_SIZE_BYTES / (1024 * 1024)
        return ValidationResult(
            is_valid=False,
            file_type=file_type,
            error=f"File exceeds the {mb:.0f} MB size limit.",
        )

    return ValidationResult(is_valid=True, file_type=file_type)