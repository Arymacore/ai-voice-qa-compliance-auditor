# AI Voice QA & Compliance Auditor — Group 9

Automatically transcribes and audits 100% of customer service calls for
required disclosures, prohibited language, and agent tone — instead of the
1–2% manual sample most call centers can afford to review today.

**Team:** Aryma Rawat, Maansi Arun Kalwar

## Status: Sprint 1 (Foundation & Ingestion)

Currently implemented:
- File validation for uploaded audio (`.wav`, `.mp3`, `.m4a`) and text (`.txt`) call files
- Transcription pipeline: Whisper API for audio, direct read for pre-transcribed text
- Sample compliant / non-compliant call transcripts for testing
- Unit tests covering the ingestion pipeline (7/7 passing)

Not yet implemented (upcoming sprints): disclosure/prohibited-language
detection, tone scoring, dashboard, cloud deployment.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # then fill in your own OPENAI_API_KEY
```

## Running the ingestion pipeline

```bash
python -m src.ingestion.pipeline data/sample/call_001_compliant.txt
```

## Running tests

```bash
python -m pytest tests/ -v
```

## Project structure

```
/src
  /ingestion   — file validation, transcription (Sprint 1)
  /detection   — disclosure & prohibited-language detection (Sprint 2)
  /scoring     — tone/sentiment scoring (Sprint 3)
  /dashboard   — review UI (Sprint 4)
/data/sample   — sample/synthetic call transcripts (no real PII)
/tests         — unit tests
/docs          — architecture, roadmap, security notes
```