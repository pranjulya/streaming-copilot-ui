# Phase 01 — Persistence and conversation API

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans. Requires Phase 00 merged.

**Goal:** Ownership-scoped conversation CRUD, pagination, archive/rename, and idempotent create on real PostgreSQL.

**Architecture:** SQLAlchemy 2 models + Alembic. Repositories filter by `Actor.user_id` in every query. Routes map domain errors to problem+json.

**Spec:** `docs/persistence-model.md` conversations/messages (user rows only), `docs/api-and-stream-contracts.md` conversation endpoints, `docs/configuration.md` auth for development.

## Files

- Create: `services/api/alembic.ini`, `services/api/alembic/versions/*_conversations.py`
- Create: `services/api/app/persistence/models.py`, `session.py`, `conversations.py`
- Create: `services/api/app/chat/conversations.py`
- Create: `services/api/app/api/conversations.py`, `errors.py`, `auth.py`
- Test: `services/api/tests/test_conversations.py`

### Task 1: Schema and models

- [ ] **Step 1:** Failing integration test: insert two users’ conversations; query by user A returns only A.
- [ ] **Step 2:** Run test — fail (no tables).
- [ ] **Step 3:** Alembic revision for `conversations` and `messages` as specified (including user-message checks). Do not add `response_runs` yet unless required by FK; if you add the table, leave it unused.
- [ ] **Step 4:** `alembic upgrade head` against Compose Postgres; test pass.
- [ ] **Step 5:** Commit `feat: add conversation and message tables`.

### Task 2: Auth adapter (development)

- [ ] **Step 1:** Test: missing actor → 401 `unauthenticated`; `X-Dev-User: alice` scopes rows to `alice`; production settings with `APP_ENV=production` and no JWT config fail startup.
- [ ] **Step 2:** Implement `Actor` extraction. Reject `X-Dev-User` unless `APP_ENV=development`.
- [ ] **Step 3:** Tests pass. Commit `feat: add development identity adapter`.

### Task 3: Conversation HTTP API

**Interfaces produced:**

```python
async def create_conversation(cmd: CreateConversation, actor: Actor) -> Conversation
async def list_conversations(actor: Actor, cursor: str | None, limit: int, include_archived: bool) -> Page[Conversation]
async def get_conversation(id: UUID, actor: Actor, msg_cursor: str | None) -> ConversationSnapshot
async def patch_conversation(id: UUID, patch: ConversationPatch, actor: Actor, key: UUID) -> Conversation
```

- [ ] **Step 1:** Tests (real DB):
  - Create, list newest-first, opaque `next_cursor`.
  - `GET` other user’s id → 404, not 403.
  - `PATCH` title; `PATCH archived true` hides from default list; `archived false` restores.
  - Duplicate `Idempotency-Key` same body returns the same conversation; different title → 409 `idempotency_key_conflict`.
  - Default title `"New conversation"` when omitted.
  - `limit=0` or `101` → 400 `validation_failed`.
- [ ] **Step 2:** Run tests — fail.
- [ ] **Step 3:** Implement repositories, service, routes, problem mapper (`docs/api-and-stream-contracts.md` catalog).
- [ ] **Step 4:** Tests pass. Commit `feat: add conversation crud with ownership and idempotency`.

## Stop gate

All tests use real PostgreSQL. Cross-user 404 is proven. Pagination does not require the client to parse the cursor.
