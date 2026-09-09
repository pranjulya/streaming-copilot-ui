# Requirements to phase traceability

Every PRD requirement maps to at least one implementation phase. Phase 08 is evidence, not a substitute for earlier proof.

| PRD item | Spec | Phase |
|---|---|---|
| Create/list/read/rename/archive conversations | contracts, persistence | 01 |
| Opaque pagination | contracts | 01 |
| Default title from first user message | contracts | 01, 03 |
| Optimistic user UUID + idempotent POST | contracts, resilience | 01, 05 |
| Typed NDJSON, split-chunk parse | contracts, LLD parser | 00, 05 |
| Display deltas, reconcile IDs/final text | reducer, contracts | 05 |
| Ignore unknown compatible events | contracts | 00, 05 |
| Abort local + canonical cancel | resilience, contracts | 06 |
| Retry failed/cancelled without new user message | persistence retry | 02, 06 |
| Regenerate new version, one visible answer | persistence | 02, 06 |
| Restore after refresh | resilience | 06 |
| Error classes | problem catalog | 01–07 |
| Preserve partial on failure | persistence complete/fail | 02, 03 |
| Fallback to history + retry | resilience degradation | 06 |
| Chat shell, keyboard, live region, reduced motion | LLD a11y | 04, 06 |
| Archive recoverable | PATCH archived | 01, 04 |
| SLOs (terminal %, idempotency, TTFE, cancel, match, authz, fixtures) | PRD §7 | 08 (measured); 00–07 (instrument + tests) |
| Auth boundary + local identity | configuration, security | 00, 07 |
| Postgres only stateful dep | HLD | 00 |
| One active run / conversation | persistence index | 02 |
| Sanitized Markdown | LLD 7b | 04 |
| Server-side provider credentials | configuration | 03, 07 |
| Same-site preferred topology | configuration | 00, 07 |
| Acceptance journey | PRD §9 | 05–06 e2e |
| Release gate | PRD §10 | 08 |

Deferred on purpose (not missing): tools, RAG, branching, websockets, identity provider, user hard-delete API, second model selector, Redis/queue.
