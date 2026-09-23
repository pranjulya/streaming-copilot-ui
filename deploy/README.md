# Deploy topology (V1)

`Caddyfile` is the reference edge configuration. It encodes the topology from
`docs/configuration.md`:

| Surface | Exposure |
|---|---|
| `/` (Next.js app) | Public web origin |
| `/v1/*` | Reverse-proxied to the API, same site as the web origin |
| `/health/live` | Public (load balancers may probe it) |
| `/health/ready` | Private network only; the edge returns 404 |
| `/metrics` | Private network only; the edge returns 404 |

Streaming routes disable proxy buffering (`flush_interval -1`) so NDJSON is not
held back by the edge.

## Secrets

- `XAI_API_KEY`, `DATABASE_URL`, and the JWT settings are injected as environment
  variables by the platform's secret store. They are never baked into images,
  never passed to the web container, and never written to disk.
- The web container needs no secrets: `NEXT_PUBLIC_API_BASE` is empty because the
  edge serves the API on the same origin.

## Containers

Two long-lived services (`web`, `api`) plus managed PostgreSQL. V1 deliberately
has no queue, no Redis, and no worker tier — a single API process supervises
generation, and multiple replicas are safe only through the lease/reaper
mechanisms described in `docs/resilience-and-reconciliation.md`.
