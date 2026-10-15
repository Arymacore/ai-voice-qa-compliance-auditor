Project documentation
# AI Voice QA & Compliance Auditor

Group 9 | Aryma Rawat, Maansi Arun Kalwar

An AI tool that transcribes call center audio and automatically flags
missing disclosures, prohibited language, and poor agent tone.

## Folders
- docs/ : architecture notes, roadmap, sprint plans, security notes
- src/ingestion/ : audio/transcript upload and speech-to-text
- src/detection/ : disclosure and prohibited-language detection
- src/scoring/ : tone/sentiment and combined compliance score
- src/dashboard/ : frontend for reviewing flagged calls
- data/sample/ : fake/synthetic transcripts only (no real personal data)

## Setup
(Coming soon)

## Security
Never commit API keys, passwords, or real customer data. Use environment
variables instead.
