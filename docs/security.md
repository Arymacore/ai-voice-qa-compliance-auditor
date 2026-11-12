# Security review

Status as of 2026-11-12. "Done" means verified in code, a test, or the live site. "Open" means not done or not yet verified.

| Area | Control | Status |
|---|---|---|
| Secrets | OpenAI key, database URL and dashboard login are read from environment variables, never stored in the repo | Done |
| Secrets | .env and data/calls.db are excluded from git and from the Docker image (.dockerignore) | Done |
| Secrets | On the host, secrets live in Render's environment settings | Done |
| Login | App refuses to start without DASHBOARD_USER and DASHBOARD_PASSWORD; there is no default | Done |
| Login | Sign-in page with a signed session cookie (HttpOnly, SameSite=Strict, Secure over HTTPS, 8 hour expiry); credentials compared in constant time | Done |
| Login | Pages redirect to /login and API calls return 401 when not signed in; covered by tests/test_login.py | Done |
| Input validation | Uploads are checked for file extension and size (MAX_FILE_SIZE_BYTES), filenames are sanitized, files are processed from a temp folder | Done |
| Output safety | Dashboard renders transcripts as plain text, never as markup | Done |
| Headers | Content-Security-Policy, X-Content-Type-Options, X-Frame-Options, Referrer-Policy and Cache-Control: no-store on every response | Done |
| Rate limiting | Uploads are capped at UPLOADS_PER_HOUR (default 20); covered by tests/test_rate_limit.py | Done |
| Transport | The public site is served over HTTPS by Render; the database connection uses sslmode=require | Done |
| PII | Demo data is synthetic sample transcripts; no real customer data is stored | Done (team to confirm) |
| Cost control | Rate limit caps paid API calls; OpenAI account uses prepaid credit with auto-recharge off | Open (verify in OpenAI billing) |
| Dependencies | requirements.txt uses minimum versions (>=), not exact pins | Open |

## Known limitations

- Authentication is a single shared login. There are no individual accounts, no lockout after failed attempts, and the account menu shows the one configured username.
- Sessions are stateless signed cookies. Signing out clears the cookie in the browser, but a copied cookie stays valid until it expires. Changing the dashboard password invalidates all sessions.
- The demo password is simple and shared with the team. The repository's tests use separate test passwords. This is accepted for a demo holding only synthetic data, and it would be replaced before real use.
- The rate limiter is global and held in memory. It resets when the service restarts and works only with a single instance.
- The free Render instance sleeps after 15 minutes idle, and the free Neon database suspends when idle, so the first request can be slow.

## Recommended before real use

Individual accounts with hashed passwords, a strong generated password, login attempt lockout, per-user rate limits, server-side session revocation, pinned dependencies, and an OpenAI spending limit.

## Known model limitation: call 006

On call_006_explicit_threat the model flags rule P2 (pressure tactics) for "Then make the payment.", a firm payment demand that is not clearly abusive. The call's FAIL status is correct, because rule P1 (threat of lawsuit and wage garnishment) applies independently, so the over-flag affects the score and the violation count but not the outcome. The model also gave an empathy rating of 1 without a supporting quote. Flagged calls go to human review, so this error is on the cautious side. It was not fixed because changing the prompt risks shifting the other sample calls.

## Known model limitation: call 006

On call_006_explicit_threat the model flags rule P2 (pressure tactics) for "Then make the payment.", a firm payment demand that the answer key marks as acceptable. The call's FAIL status is correct, because rule P1 (threat of lawsuit and wage garnishment) applies independently, so the error does not change the outcome. It is the only rule-level error in the full run (83/84 rules correct, 14/14 call statuses correct). Flagged calls go to human review, so the error is on the cautious side. It was not fixed because a prompt change risks shifting the other sample calls. The model also gave an empathy rating of 1 on this call without a supporting quote.
