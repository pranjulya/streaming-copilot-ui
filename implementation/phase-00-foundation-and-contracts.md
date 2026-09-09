# Phase 00 — Foundation and contracts

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Do not start until the planning package is explicitly approved.

**Goal:** Runnable web and API processes, local PostgreSQL, and frozen V1 stream fixtures that both sides must accept.

**Architecture:** Empty Next.js app and FastAPI app share one Compose Postgres. No chat behavior yet. Contracts are fixtures + JSON Schema + OpenAPI snapshot.

**Tech stack:** Python 3.12, Node 22, Next 15, FastAPI, PostgreSQL 16, pytest, Vitest. See `docs/configuration.md`.

**Spec:** `docs/api-and-stream-contracts.md`, `docs/configuration.md`, `docs/LLD.md` §1, `docs/HLD.md`.

## Global constraints

- Same-origin: Next rewrites `/v1` and `/health/*` to the API in development.
- Development identity only when `APP_ENV=development`.
- Do not call a real LLM in this phase.
- Do not introduce a monorepo framework.

## Files

- Create: `docker-compose.yml`
- Create: `.env.example`, `.gitignore`
- Create: `services/api/pyproject.toml`, `services/api/app/main.py`, `services/api/app/api/health.py`, `services/api/app/settings.py`, `services/api/tests/test_health.py`
- Create: `apps/web/package.json`, `apps/web/app/page.tsx`, `apps/web/next.config.ts`
- Create: `contracts/stream-events.schema.json`, `contracts/openapi.yaml`, `contracts/examples/*.json`
- Create: `contracts/tests/test_fixtures.py` or `scripts/validate-contracts.mjs`
- Create: `README` local-run section (root README)

### Task 1: Local Postgres and gitignore

**Produces:** Compose file that answers `pg_isready`.

- [ ] **Step 1:** Add `docker-compose.yml` with `postgres:16`, user/password/db `copilot`, port `5432`, healthcheck `pg_isready -U copilot`.
- [ ] **Step 2:** Add `.gitignore` for `.env`, `node_modules`, `.next`, `__pycache__`, `.venv`, `postgres_data`.
- [ ] **Step 3:** Add `.env.example` matching `docs/configuration.md` local defaults.
- [ ] **Step 4:** Run `docker compose up -d` and `docker compose exec postgres pg_isready -U copilot`. Expected: accept connections.
- [ ] **Step 5:** Commit `chore: add local postgres and env example`.

### Task 2: FastAPI health

**Produces:** `GET /health/live` and `GET /health/ready`.

- [ ] **Step 1:** Write failing test `services/api/tests/test_health.py`:

```python
def test_live_ok(client):
    r = client.get("/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "live"}

def test_ready_requires_db(client):
    r = client.get("/health/ready")
    assert r.status_code in (200, 503)
    assert r.headers["content-type"].startswith("application/json") or "problem+json" in r.headers["content-type"]
```

- [ ] **Step 2:** Run `pytest services/api/tests/test_health.py -v` — expect fail (no app).
- [ ] **Step 3:** Implement `Settings` from env, async engine, `app/api/health.py`, include router in `main.py`. Ready runs `SELECT 1`.
- [ ] **Step 4:** Re-run tests against Compose Postgres — pass.
- [ ] **Step 5:** Commit `feat: add api health endpoints`.

### Task 3: Next.js shell and rewrite

**Produces:** `http://127.0.0.1:3000` renders a placeholder; `/health/live` proxies to the API.

- [ ] **Step 1:** Scaffold `apps/web` with Next 15 App Router. `next.config.ts` rewrites `/v1/:path*` and `/health/:path*` to `http://127.0.0.1:8000`.
- [ ] **Step 2:** `app/page.tsx` shows “Copilot” heading only (no chat).
- [ ] **Step 3:** Run `pnpm dev` and `curl -s http://127.0.0.1:3000/health/live` — `{"status":"live"}`.
- [ ] **Step 4:** Commit `feat: add web shell with same-origin rewrites`.

### Task 4: Frozen stream fixtures

**Produces:** One JSON file per V1 event type plus heartbeat and snapshot.

- [ ] **Step 1:** Create `contracts/examples/` files: `response.started.json`, `message.delta.json`, `usage.updated.json`, `heartbeat.json`, `message.completed.json`, `response.completed.json`, `response.cancelled.json`, `response.failed.json`, `response.snapshot.json`. Each file is one envelope matching `docs/api-and-stream-contracts.md`. Heartbeat `sequence` equals `data.last_sequence`. Snapshot `sequence` equals `data.last_sequence`.
- [ ] **Step 2:** Write `contracts/stream-events.schema.json` covering envelope required keys and a discriminator on `type`.
- [ ] **Step 3:** Write a validator test that loads every example and asserts schema success, unique `type` coverage, `protocol_version=1.0`, and LF-serializable `json.dumps(...) + "\n"`.
- [ ] **Step 4:** Add stub `contracts/openapi.yaml` listing every path in the contracts table with problem+json error responses. No codegen.
- [ ] **Step 5:** Run the validator — pass. Commit `feat: freeze v1 stream fixtures and schemas`.

## Stop gate

Health checks pass through the Next rewrite. Fixture suite covers every V1 type including `response.snapshot`. Reviewer confirms no chat/provider code landed.
