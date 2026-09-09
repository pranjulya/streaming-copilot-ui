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

- [ ] Production startup requires JWKS/issuer/audience.
- [ ] Invalid token → 401; valid `sub` scopes queries.
- [ ] If `AUTH_COOKIE_NAME` set: cookie holds the JWT; mutations without `Authorization` require `X-CSRF-Token` matching `csrf_token` cookie and `Origin` in `ALLOWED_ORIGINS`.
- [ ] Dev adapter still refused when `APP_ENV!=development`.
- [ ] Commit `feat: validate host jwt at the api boundary`.

### Task 2: Rate limits and bounds

- [ ] Per-user `CREATE_RESPONSE_PER_MINUTE` in **process memory** (not Postgres) on create/retry/regenerate → 429 + `Retry-After` + rate-limit headers. Document that N replicas multiply the effective cluster quota in V1.
- [ ] `MAX_REQUEST_BYTES` → 413.
- [ ] `MAX_MESSAGE_CHARS` already 400.
- [ ] Commit `feat: rate limit and body bounds`.

### Task 3: Telemetry

- [ ] Metrics from the observability name table.
- [ ] Logs include correlation IDs; caplog tests fail if prompt/response substrings appear.
- [ ] `user_id` hashed; raw identity not logged.
- [ ] Traces omit provider text.
- [ ] Commit `feat: add copilot metrics logs and traces`.

### Task 4: Browser security

- [ ] CSP and headers from `docs/security.md`.
- [ ] CORS allow-list tests: credentialed wildcard rejected.
- [ ] Markdown XSS suite in CI.
- [ ] Commit `feat: lock browser security headers and cors`.

### Task 5: Deploy topology

- [ ] Document edge: web origin, `/v1` proxy, `/health/live` public, `/health/ready` private.
- [ ] Secret injection via env, not files in the image.
- [ ] Dependency and secret scanning in CI.
- [ ] Commit `feat: production topology and scanning`.

## Stop gate

Ownership/XSS/telemetry/deploy checks pass. No prompt text in standard log snapshots.
