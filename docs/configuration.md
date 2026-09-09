# Configuration and Local Runtime

Named settings, local compose, and safe defaults. Numeric timeouts, flush batches, and retention windows are **calibrated in Phase 08**; local defaults below are only for development.

V1 has no feature flags.

## 1. Runtime topology (local)

| Process | Bind | Notes |
|---|---|---|
| Next.js | `http://127.0.0.1:3000` | Browser origin |
| FastAPI | `http://127.0.0.1:8000` | Browser calls `/v1` via Next.js rewrite `/v1` → API, same site |
| PostgreSQL 16 | `127.0.0.1:5432` | Compose service `postgres` |

`docker-compose.yml` (introduced in Phase 00):

- Image: `postgres:16`
- Database/user/password: `copilot` / `copilot` / `copilot` (local only)
- Healthcheck: `pg_isready`
- Volume: `postgres_data`

Same-site production: the edge serves `apps/web` and reverse-proxies `/v1` and `/health/live` to FastAPI. `/health/ready` is reachable only on the private network.

## 2. Environment catalog

Prefix `COPILOT_` is unused; names below are canonical. Web bundles receive **only** `NEXT_PUBLIC_API_BASE` (empty string when same-origin).

| Name | Required | Local default | Secret | Purpose |
|---|---|---|---|---|
| `APP_ENV` | yes | `development` | no | `development` / `staging` / `production` |
| `LOG_LEVEL` | no | `INFO` | no | Structured log level |
| `DATABASE_URL` | yes | `postgresql+asyncpg://copilot:copilot@127.0.0.1:5432/copilot` | yes in non-dev | SQLAlchemy URL |
| `INSTANCE_ID` | no | random UUID at boot | no | Lease owner identity; not required to be stable across restarts because NULL/expired leases are recovered |
| `XAI_API_KEY` | production yes | unset | yes | xAI credential; never in the web bundle |
| `XAI_BASE_URL` | no | `https://api.x.ai/v1` | no | Provider origin |
| `XAI_MODEL` | no | `grok-4.6` | no | Deployment-fixed model |
| `SYSTEM_PROMPT` | no | see §4 | no | Server-side instruction; not logged |
| `DEV_USER_ID` | dev only | `dev-user` | no | Default local actor |
| `AUTH_JWT_ISSUER` | non-dev yes | unset | no | JWT `iss` |
| `AUTH_JWT_AUDIENCE` | non-dev yes | unset | no | JWT `aud` |
| `AUTH_JWT_JWKS_URL` | non-dev yes | unset | no | JWKS |
| `AUTH_JWT_SUBJECT_CLAIM` | no | `sub` | no | Actor user id claim |
| `AUTH_COOKIE_NAME` | no | unset | no | If set, cookie session is accepted after JWT |
| `ALLOWED_ORIGINS` | yes | `http://127.0.0.1:3000` | no | CORS allow-list, comma-separated |
| `MAX_MESSAGE_CHARS` | no | `8000` | no | User turn cap |
| `MAX_OUTPUT_CHARS` | no | `100000` | no | Assistant cap; exceed → `output_limit_exceeded` |
| `MAX_REQUEST_BYTES` | no | `65536` | no | JSON body cap |
| `CONTEXT_CHAR_BUDGET` | no | `120000` | no | Conservative context ceiling |
| `MAX_ACTIVE_RUNS_PER_USER` | no | `3` | no | Concurrent active runs across conversations |
| `CREATE_RESPONSE_PER_MINUTE` | no | `20` | no | Per-user send/retry/regenerate rate (best-effort **per API process**; V1 has no cluster-wide counter) |
| `LEASE_SECONDS` | no | `15` | no | Generation ownership lease |
| `LEASE_RENEW_SECONDS` | no | `5` | no | Renew interval |
| `PROVIDER_CONNECT_TIMEOUT_SECONDS` | no | `10` | no | Local; Phase 08 may change |
| `PROVIDER_IDLE_TIMEOUT_SECONDS` | no | `30` | no | Local |
| `GENERATION_TIMEOUT_SECONDS` | no | `120` | no | Local |
| `HEARTBEAT_INTERVAL_SECONDS` | no | `15` | no | Connection-only heartbeat |
| `EVENT_FOLLOW_POLL_MS` | no | `50` | no | Follower poll; LISTEN/NOTIFY optional later |
| `DELTA_FLUSH_MS` | no | `40` | no | Batch flush timer |
| `DELTA_FLUSH_CHARS` | no | `24` | no | Batch flush size |
| `SHUTDOWN_GRACE_SECONDS` | no | `10` | no | Drain window |
| `EVENT_RETENTION_HOURS` | no | `24` | no | Compact terminal runs after this |
| `IDEMPOTENCY_TTL_HOURS` | no | `24` | no | Key retention after run terminal |
| `NEXT_PUBLIC_API_BASE` | no | `""` | no | Empty = same origin |

Startup **fails** if `APP_ENV` is not `development` and `XAI_API_KEY`, `DATABASE_URL`, or JWT settings are missing. Startup **fails** if `APP_ENV!=development` and a development identity adapter is configured.

## 3. Package and quality tooling (Phase 00 pins)

- API: `uv` or `pip-tools` lockfile; `ruff`, `mypy --strict` on `app/`.
- Web: `pnpm`; `eslint`, `prettier`, `tsc --noEmit`.
- CI: fixture schema check, unit, API+Postgres integration, Playwright smoke after Phase 05, secret scan, dependency scan after Phase 07.
- No monorepo framework. Two packages, one compose file, one CI workflow.

## 4. System prompt (V1)

Stored only in configuration, not the database:

> You are a helpful Copilot. Answer in Markdown. Do not claim tool use, browsing, or private chain-of-thought. If you are unsure, say so.

Changing the prompt is a configuration deploy, not a schema migration. Prompt text is excluded from telemetry.

## 5. Problem type URLs

`type` in problem+json is `https://copilot.local/problems/{code}` where `{code}` matches the catalog in `docs/api-and-stream-contracts.md`. The host is a stable identifier, not a deployed website.

## 6. Load-test shape (Phase 08 records the accepted numbers)

Until Phase 08, the **planning target** used to size local soak tests is:

- 50 concurrent active streams
- 5 new `create_response` requests per second
- Mix: 70% complete under 5s fake-provider, 20% 30s streams, 10% cancel/retry

PRD latency SLOs remain the release bar; this shape is not a traffic forecast.
