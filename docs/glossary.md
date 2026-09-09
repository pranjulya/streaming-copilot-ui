# Glossary

| Term | Meaning |
|---|---|
| Canonical state | Rows committed in PostgreSQL for conversations, messages, runs, and events |
| Response run | One generation attempt; immutable after a terminal status |
| Sequence | Per-run monotonically increasing cursor starting at 1 |
| Idempotency key | Client UUID scoped to `(user_id, operation)` so retries do not duplicate writes |
| Owner lease | `owner_instance_id` + `lease_expires_at` proving which API process generates a run |
| Follower | HTTP handler that reads committed events and writes NDJSON to one client |
| Supervisor | In-process task that calls the provider and commits events |
| Reconciliation | Client algorithm that replaces optimistic/partial UI with canonical state |
| Snapshot event | Synthesized replay record when retained events no longer cover `after_sequence` |
| Heartbeat | Connection-only keepalive; not stored; ignored by the reducer |
| FakeProvider | Deterministic test/local adapter that yields scripted deltas and failures |
| Actor | Authenticated `{user_id, auth_method}` extracted at the HTTP boundary |
