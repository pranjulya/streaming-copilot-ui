# Phase 07 — Production guardrails

> Requires Phase 06 functionally complete.

**Goal:** Authz, XSS, rate limits, security headers, secrets, telemetry without content, and a deployable topology.

**Spec:** `docs/security.md`, `docs/observability.md`, `docs/configuration.md`, `docs/production-scenarios.md`.

## Files

- Create: `services/api/app/api/auth_jwt.py`, `rate_limit.py`
- Create: `services/api/app/observability/{logging,metrics,tracing}.py`
- Create: `apps/web/middleware.ts` (security headers)
- Create: `deploy/` compose or edge config as chosen in this phase (document in `docs/configuration.md` if a path is added)
- Test: ownership matrix, XSS corpus, log-redaction, CORS

### Task 1: JWT adapter and CSRF

- [x] Production startup requires JWKS/issuer/audience.
- [x] Invalid token → 401; valid `sub` scopes queries.
- [x] If `AUTH_COOKIE_NAME` set: cookie holds the JWT; mutations without `Authorization` require `X-CSRF-Token` matching `csrf_token` cookie and `Origin` in `ALLOWED_ORIGINS`.
- [x] Dev adapter still refused when `APP_ENV!=development`.
- [x] Commit `feat: validate host jwt at the api boundary`.

### Task 2: Rate limits and bounds

- [x] Per-user `CREATE_RESPONSE_PER_MINUTE` in **process memory** (not Postgres) on create/retry/regenerate → 429 + `Retry-After` + rate-limit headers. Document that N replicas multiply the effective cluster quota in V1.
- [x] `MAX_REQUEST_BYTES` → 413.
- [x] `MAX_MESSAGE_CHARS` already 400.
- [x] Commit `feat: rate limit and body bounds`.

### Task 3: Telemetry

- [x] Metrics from the observability name table.
- [x] Logs include correlation IDs; caplog tests fail if prompt/response substrings appear.
- [x] `user_id` hashed; raw identity not logged.
- [x] Traces omit provider text.
- [x] Commit `feat: add copilot metrics logs and traces`.

### Task 4: Browser security

- [x] CSP and headers from `docs/security.md`.
- [x] CORS allow-list tests: credentialed wildcard rejected.
- [x] Markdown XSS suite in CI.
- [x] Commit `feat: lock browser security headers and cors`.

### Task 5: Deploy topology

- [x] Document edge: web origin, `/v1` proxy, `/health/live` public, `/health/ready` private.
- [x] Secret injection via env, not files in the image.
- [x] Dependency and secret scanning in CI.
- [x] Commit `feat: production topology and scanning`.

## Stop gate

Ownership/XSS/telemetry/deploy checks pass. No prompt text in standard log snapshots.
