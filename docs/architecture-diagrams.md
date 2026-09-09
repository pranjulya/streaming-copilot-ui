# Architecture Diagrams

## System context

```mermaid
flowchart LR
    U[Signed-in user] --> W[Next.js web app]
    W -->|JSON + NDJSON over HTTPS| A[FastAPI service]
    A -->|SQL transactions| P[(PostgreSQL)]
    A -->|Server-side streaming API| L[LLM provider]
    O[Operations team] --> D[Logs metrics traces alerts]
    A --> D
    W --> D
```

## Backend containers

```mermaid
flowchart TB
    R[FastAPI routes] --> C[Conversation service]
    R --> S[Response service]
    S --> G[Generation supervisor]
    G --> V[Single provider adapter]
    C --> Q[Repositories]
    S --> Q
    G --> E[Transactional event writer]
    E --> Q
    Q --> DB[(PostgreSQL)]
    F[Event follower] --> DB
    R --> F
```

## Send and stream sequence

```mermaid
sequenceDiagram
    actor User
    participant Web
    participant API
    participant DB as PostgreSQL
    participant Gen as Generation task
    participant LLM as LLM provider

    User->>Web: Send message
    Web->>Web: Add optimistic user + assistant placeholder
    Web->>API: POST response + idempotency key
    API->>DB: Create/find message and run
    DB-->>API: Canonical IDs
    API->>Gen: Start run once
    API-->>Web: NDJSON response
    Gen->>LLM: Open provider stream
    LLM-->>Gen: Text delta
    Gen->>DB: Commit content + sequenced event
    API->>DB: Follow committed events
    DB-->>API: Event rows
    API-->>Web: response.started / message.delta
    Web->>Web: Reconcile IDs and append delta
    LLM-->>Gen: Complete + usage
    Gen->>DB: Commit final content + terminal events
    API-->>Web: message.completed / response.completed
    Web->>Web: Replace with canonical final content
```

## Disconnect and replay

```mermaid
sequenceDiagram
    participant Web
    participant API1 as API replica A
    participant DB as PostgreSQL
    participant API2 as API replica B

    Web-xAPI1: Connection drops after sequence 17
    API1->>DB: Generation continues committing events
    Web->>API2: GET canonical run
    API2->>DB: Read status and last sequence
    DB-->>API2: streaming, sequence 24
    Web->>API2: POST stream after_sequence=17
    API2->>DB: Replay 18..24 and follow
    API2-->>Web: Deduplicated ordered NDJSON
```

## Cancel race

```mermaid
sequenceDiagram
    actor User
    participant Web
    participant API
    participant DB
    participant Gen

    User->>Web: Stop
    Web->>Web: Abort local reader; show stopping
    Web->>API: POST cancel
    API->>DB: Set cancel_requested_at
    API-->>Web: Current run snapshot
    Gen->>DB: Observe cancel at next boundary
    Gen->>Gen: Close provider stream
    Gen->>DB: Commit partial + response.cancelled
    Web->>API: Reconcile/follow
    API-->>Web: Canonical cancelled state
```

## Trust boundaries

```mermaid
flowchart LR
    B[Untrusted browser input] -->|validation, authn, CSRF/rate limits| A[API trust boundary]
    A -->|ownership-scoped SQL| D[(Protected database)]
    A -->|minimum prompt + secret credential| P[External provider]
    P -->|untrusted model output| S[Sanitize Markdown in browser]
    S --> V[Rendered transcript]
```
