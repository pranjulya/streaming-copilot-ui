# Operator runbook (Phase 08)

A dry-run of the operator template from `docs/production-scenarios.md` against the
V1 behavior. Each scenario names the signal to watch, the first action, and what
"healthy again" looks like. Nothing here invents architecture; every mechanism
exists in Phases 00–07.

| # | Scenario | Signal | First action | Healthy again |
|--:|---|---|---|---|
| 1 | Provider latency spike | `copilot_service_first_event_seconds` p95 up; streams slow | Watch `copilot_provider_timeout` failures; the idle timeout fails runs safely with partial text | p95 back under the PRD bar; retries succeed |
| 2 | Provider 429/5xx mid-stream | `copilot_runs_terminal_total{error_code=~"provider_.*"}` rising | Confirm partial text retained; users see Retry | error rate back to baseline |
| 3 | Database unavailable | `/health/ready` 503; `service_unavailable` responses | Fix Postgres; the API keeps serving liveness | ready 200; no active runs stuck (reaper clears leases) |
| 4 | API replica termination | `copilot_runs_orphaned_total` increase; clients reconciling | Let another replica's periodic reaper expire the leases; users reload to canonical history | orphans stop rising; reconnects complete |
| 5 | Network loss during generation | Client shows reconnecting; no duplicate text | Nothing server-side: generation continues; the client resumes from its cursor | catch-up completes; one canonical answer |
| 6 | Cancel races completion | `copilot_cancel_ack_seconds` fine; UI may show completed | None: canonical state wins by design; the cancel no-ops | UI shows completed or cancelled — never a lie |
| 7 | Duplicate submit/browser retry | `copilot_idempotency_hits_total{result="replay"}` | None: the same key returns the same run; `conversation_busy` points the client at the active run | exactly one user message |
| 8 | Slow consumer | follower latency; event table growth | Retention (`EVENT_RETENTION_HOURS`) bounds rows; snapshots replace missed windows | consumer caught up or stream closed cleanly |
| 9 | Proxy buffers chunks | first event late though generated | Confirm `X-Accel-Buffering: no` reaches the edge; deploy `deploy/Caddyfile` (streaming routes unbuffered) | first event prompt again |
| 10 | Event table growth | `copilot_events_emitted_total` vs retention | Check `EVENT_RETENTION_HOURS`; compact terminal runs | growth bounded |
| 11 | Bad deployment or migration | deploy checks failing; readiness red | Roll back the app image (forward-only migrations tolerate older code); rehearse restore with `scripts/rehearse_restore.sh` | readiness green on the previous version |
| 12 | Suspected data exposure | security alert | Check logs for content leakage (should be none by design); rotate secrets; involve the security owner | root cause recorded; rotation complete |
| 13 | Cost anomaly | `copilot_tokens_total` spike | Inspect run volume vs tokens per run; check `MAX_OUTPUT_CHARS` behavior | token rate back to baseline |
| 14 | Model quality regression | user reports; eval set drift | Run `eval/run_eval.py` in live mode manually and compare with the last report; adjust the system prompt via config deploy | eval comparison acceptable |

## Template

For any incident: (1) user impact, (2) stable `code`/`error_code`, (3) diagnostic id
from the problem response, (4) which invariant held or failed, (5) rollback or
config change, (6) follow-up test that would have caught it.

## Practical commands

```sh
docker compose ps                                   # local Postgres health
curl -fsS http://127.0.0.1:8000/health/ready        # private readiness
uv run --project services/api python scripts/smoke.py --require-db
./scripts/rehearse_restore.sh postgresql://copilot:copilot@127.0.0.1:5433/copilot
```
