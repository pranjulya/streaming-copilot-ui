# Security and Privacy

## 1. Trust boundaries

Browser requests, model output, provider errors, Markdown, event payloads, and identifiers supplied in URLs are untrusted. Authentication proves an actor; every resource lookup must also prove ownership.

## 2. Authentication and authorization

- Integrate with the host product's authenticated session/JWT; do not build an identity provider. See ADR-014 and `docs/configuration.md`.
- Validate issuer, audience, signature, expiry, and required subject at the API boundary.
- Scope every conversation/message/run query by authenticated `user_id`.
- Return `401 unauthenticated` when no valid actor is present; return `404` for missing and not-owned resources.
- Never trust `user_id` from request bodies or client metadata.
- Local development identity is impossible to enable in production configuration.
- One active run **per conversation** (database unique index) and at most `MAX_ACTIVE_RUNS_PER_USER` active runs **per user** (application check before insert). Two conversations may stream at once unless the per-user cap is reached (`409 too_many_active_runs`). Timed send rate uses `429 rate_limited`.

## 3. Browser protections

- Prefer secure, HTTP-only, same-site cookies behind a same-site API.
- If cookies authenticate mutations, require CSRF protection and verify `Origin`.
- Restrict CORS to explicit production origins; never combine wildcard origins with credentials.
- Apply these headers on the web origin: `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, `Permissions-Policy: camera=(), microphone=(), geolocation=()`.
- Render Markdown without raw HTML and sanitize links/protocols.
- Do not place provider keys, database credentials, or privileged diagnostics in the web bundle.

## 4. Input and resource controls

- Bound request body, message length, pagination limit, concurrent active runs, total generation time, and provider output length.
- Validate UUIDs, content type, accepted protocol, and idempotency-key shape.
- Rate limit by authenticated user plus a network-level signal; do not rely solely on IP.
- Use parameterized queries and database constraints.
- Reject control characters that could corrupt logs while preserving valid Unicode content.

## 5. LLM-specific threats

- Model output is data, never executable instructions to the application.
- System prompts and provider credentials remain server-side.
- V1 has no tools, retrieval, browsing, code execution, or secret-bearing context, sharply limiting prompt-injection consequences.
- Do not expose private chain-of-thought. Safe status events may describe progress without hidden reasoning.
- When tools are added later, each tool requires explicit authorization, schema validation, least privilege, confirmation for consequential actions, and output isolation.

## 6. Data protection

- TLS in transit and managed encryption at rest.
- Secrets from a managed secret store, rotated without code changes.
- Prompt/response content excluded from default telemetry.
- Retention and deletion apply transitively to messages, runs, and stream events.
- Database backups are access-controlled and tested for restore and deletion-policy implications.

## 7. Abuse and cost controls

- Per-user active-run cap (`MAX_ACTIVE_RUNS_PER_USER`, default 3) and token/output ceilings. Exceeding the cap returns `409 too_many_active_runs`.
- Provider timeouts and circuit-breaker-style admission control based on observed failures.
- Usage accounting stored from canonical terminal metadata.
- Alerts on anomalous run volume, output tokens, repeated cancellation, and authorization failures.

## 8. Security verification

- Ownership matrix tests across every resource endpoint.
- CSRF/CORS/origin tests for the deployed auth mode.
- Markdown XSS payload suite.
- Fuzzing/property checks for NDJSON lines and request boundaries.
- Dependency and container scanning in CI.
- Secret scanning and log-content assertions.
- Threat-model review before adding tools, files, RAG, or external actions.
