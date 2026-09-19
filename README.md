# Project 6 — Streaming Copilot UI

A full chat-style Copilot with persistent history and typed NDJSON streaming, implemented in reviewed phases.

Agent entrypoint: [`AGENTS.md`](AGENTS.md) (required at repo root for Grok/SOL and other coding agents).

## Status

**Planning approved on 2026-09-19 at `53c1b7c`. Phase 00 implementation is under verification.** Later phases remain behind the Phase 00 review gate.

## Locked decisions

- Next.js/React frontend
- FastAPI backend
- `POST` streaming through `fetch()` and `ReadableStream`
- `AbortController` for client-side stream cancellation
- Server-side persistent conversation history
- Versioned typed NDJSON events
- xAI (`grok-4.6`) as the single V1 production provider; `FakeProvider` in tests
- Generation owner leases for multi-replica safety

## Planning package

- [Agent project rules](AGENTS.md)

- [Product requirements](docs/PRD.md)
- [High-level design](docs/HLD.md)
- [Low-level design](docs/LLD.md)
- [Architecture diagrams](docs/architecture-diagrams.md)
- [API and stream contracts](docs/api-and-stream-contracts.md)
- [State machines](docs/state-machine.md)
- [Persistence model](docs/persistence-model.md)
- [Resilience and reconciliation](docs/resilience-and-reconciliation.md)
- [Observability](docs/observability.md)
- [Security](docs/security.md)
- [Testing and evaluation](docs/testing-and-evaluation.md)
- [Production scenarios](docs/production-scenarios.md)
- [Architecture decisions](docs/decisions.md)
- [Configuration and local runtime](docs/configuration.md)
- [Requirements traceability](docs/traceability.md)
- [Glossary](docs/glossary.md)
- [Learning path](Learning/learning-path.md)
- [Questions and answers](Learning/questions-and-answers.md)
- [Master implementation blueprint](Implementation.md)
- [Phase index](implementation/README.md)
- Phases 00–08 under `implementation/phase-0*.md`
- [Planning review (approve, 0 open issues)](docs/_planning-review.md)

## Review gate

The complete planning package and Phase 00 were explicitly authorized in the project conversation. Review Phase 00 verification before beginning Phase 01.


## Local run (Phase 00)

Requires Python 3.12, Node 22 (`nvm use`), uv, pnpm 10.34.5, and Docker Compose. No xAI key is needed. Run commands from the repository root.

```sh
cp .env.example .env
# Install pnpm 10.34.5 using your Node package-manager setup if needed.
docker compose up -d --wait
docker compose exec postgres pg_isready -U copilot
uv sync --project services/api --locked
pnpm --dir apps/web install --frozen-lockfile
uv run --project services/api uvicorn app.main:create_app --factory --app-dir services/api --host 127.0.0.1 --port 8000
```

In a second terminal:

```sh
pnpm --dir apps/web dev
```

Open `http://127.0.0.1:3000`. It displays the “Copilot” heading; chat arrives in later phases. The API loads the root `.env` by absolute path. The web needs no secrets or root env-file copy: the development rewrite uses the same origin. In production, configure the deployment edge as documented; the development rewrites are disabled and readiness stays private.

```sh
curl --fail http://127.0.0.1:3000/health/live
curl --fail http://127.0.0.1:3000/health/ready
```

Expect `{"status":"live"}` and `{"status":"ready","database":"ok"}`. Database failure returns HTTP 503 with a safe problem response. Liveness remains HTTP 200.

## Verification

```sh
TEST_DATABASE_URL=postgresql+asyncpg://copilot:copilot@127.0.0.1:5432/copilot uv run --project services/api pytest -q
uv run --project services/api ruff check services/api
uv run --project services/api mypy --strict services/api/app
pnpm --dir apps/web test
pnpm --dir apps/web lint
pnpm --dir apps/web typecheck
pnpm --dir apps/web format:check
pnpm --dir apps/web build
```

Without `TEST_DATABASE_URL`, the real-PostgreSQL test explicitly skips; that is not a passing database gate. CI starts the shipped Compose service and runs that test. Stop the manually started web/API processes before running the self-contained smoke check:

```sh
uv run --project services/api python scripts/smoke.py --require-db
```

The smoke check starts and cleans up both processes and tests the actual development proxy and shell. Omit `--require-db` only to check degraded operation without PostgreSQL. The GitHub Actions workflow also runs the build, format, type, API, and both-language contract checks. `contracts/openapi.yaml` is a planned API stub, not the currently implemented route list.

Stop PostgreSQL with `docker compose down`; the named data volume remains intact.
