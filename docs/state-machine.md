# State Machines

## 1. Response run state

```mermaid
stateDiagram-v2
    [*] --> queued: transaction commits
    queued --> streaming: provider stream opens
    queued --> cancelling: cancel requested
    streaming --> cancelling: cancel requested
    streaming --> completed: final content committed
    queued --> failed: startup/provider failure
    streaming --> failed: provider/protocol/timeout failure
    cancelling --> cancelled: provider closed + partial persisted
    cancelling --> failed: cancellation cleanup fails
    queued --> failed: orphan recovery
    streaming --> failed: orphan recovery
    cancelling --> failed: orphan recovery
    completed --> [*]
    cancelled --> [*]
    failed --> [*]
```

Allowed states are `queued`, `streaming`, `cancelling`, `completed`, `cancelled`, and `failed`. Terminal states never transition. Retry and regenerate create a new run; they do not reopen an old run.

## 2. Client stream state

```mermaid
stateDiagram-v2
    [*] --> idle
    idle --> submitting: optimistic turn
    submitting --> connecting: HTTP accepted
    connecting --> streaming: response.started
    connecting --> reconciling: network/protocol uncertainty
    streaming --> completed: terminal completed
    streaming --> stopping: user stops
    streaming --> reconciling: disconnect/gap
    stopping --> cancelled: canonical cancellation
    stopping --> completed: completion won the race
    stopping --> reconciling: cancel outcome unknown
    reconciling --> connecting: replay/follow active run
    reconciling --> completed: canonical completed
    reconciling --> cancelled: canonical cancelled
    reconciling --> failed: canonical failed or resume unavailable
    submitting --> failed: request rejected
    connecting --> failed: terminal failure
    streaming --> failed: terminal failure
    completed --> idle
    cancelled --> idle
    failed --> idle: retry/regenerate/dismiss
```

The reducer stores state per run, not in one global loading boolean. Navigation to another conversation does not cancel a run unless the user explicitly stops it.

## 3. Message state

User messages move `optimistic → persisted` or `optimistic → rejected`. Assistant messages move `placeholder → partial → complete|cancelled|failed`. Server history can replace any non-canonical client state during reconciliation.

## 4. Transition invariants

- Apply an event only when its run ID matches and its sequence is newer.
- `response.started` must precede deltas in a fresh stream; replay may begin with `response.snapshot`.
- Only `message.delta` appends content.
- `message.completed` replaces content.
- A terminal response freezes controls except retry/regenerate.
- Cancellation shown as final only after canonical confirmation; local abort alone means “stopping” or “reconciling.”
- A sequence gap never guesses missing text; it triggers replay.
