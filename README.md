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
## Deployment

The app runs on Render (free web service, Docker) with a Neon PostgreSQL database (free plan, AWS US East 1).

Live demo: https://ai-voice-qa-compliance-auditor.onrender.com (the free instance sleeps after 15 minutes idle, so open it a couple of minutes before a demo).

### Environment variables

| Name | Purpose |
|---|---|
| DASHBOARD_USER | Dashboard login name (required, no default) |
| DASHBOARD_PASSWORD | Dashboard password (required, no default) |
| DATABASE_URL | Neon connection string, must start with `postgresql+psycopg2://` |
| OPENAI_API_KEY | OpenAI API key |
| UPLOADS_PER_HOUR | Upload rate limit, default 20 |
| SESSION_HOURS | Optional sign-in session length, default 8 |

Set these in the host's environment settings. Never commit them.

### Steps

1. Create a Neon project and copy its connection string. Change its start to `postgresql+psycopg2://`.
2. Load the sample calls into it. In PowerShell, set `$env:DATABASE_URL` to the string, run `python -m src.scoring.analysis data/sample --save`, then run `Remove-Item Env:DATABASE_URL`.
3. In Render, choose New, then Web Service, then Public Git Repository, and enter this repository's URL.
4. Set branch `main`, runtime Docker, instance type Free, region US East (Virginia), and health check path `/api/health`.
5. Add the environment variables above and deploy.
6. Open the `.onrender.com` link and sign in. After later code changes, use Manual Deploy.

See docs/security.md for the security review and known limitations.
