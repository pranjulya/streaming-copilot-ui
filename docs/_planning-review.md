## Design Document Review: Streaming Copilot UI planning package

### Summary

**approve** (round 4). Issues 1, 2, 16, 17, and the P1 periodic-reaper scope bug are fixed in the files.

Orphan recovery is split: **startup** fails this-instance non-terminal rows (even if unexpired) plus NULL/expired leases; the **periodic** reaper (`≤ LEASE_SECONDS` on every live replica) fails **only** NULL/expired leases and must not fail a healthy run this instance is renewing. `start()` only renews, and live processes must not share `INSTANCE_ID`. RunSnapshot is GET and cancel only; retry/regenerate are NDJSON and start generation only on first idempotency accept. Retry/regenerate reuse create-turn locks, cap, lease stamp, and archived check. Retry of a non-failed/cancelled run is `invalid_run_state`; regenerate while a run is active is `conversation_busy` with `active_run_id`.

There are 0 open issues. The planning package is freeze-ready for Phase 00.
