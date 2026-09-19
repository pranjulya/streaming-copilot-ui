# V1 contracts

`stream-events.schema.json` is a strict **producer** schema. The nine examples are independent event examples, not one run containing three terminal outcomes. Each example is pretty-printed JSON on disk; serialize with `JSON.stringify(event) + "\n"` or `json.dumps(event) + "\n"` for NDJSON transport.

Python (`jsonschema`) and TypeScript (`ajv`) validate the same files. Heartbeat and snapshot sequence equality is checked separately because portable JSON Schema cannot express equality between two fields. Unicode and embedded newline examples prevent accidental assumptions about bytes, UTF-16 units, or physical line boundaries.

Future consumer parsers must still ignore unknown compatible event types as specified in `docs/api-and-stream-contracts.md`. They must not use this frozen producer schema to reject every unknown event.

`openapi.yaml` is the Phase 00 design stub covering all twelve operations. Resource schemas are deliberately placeholders until their owning phase. Only the health routes run today; the API's live `/openapi.json` is consequently smaller. No generated clients or chat/provider implementation is included.

Run from the repository root:

```sh
uv run --project services/api pytest contracts/tests -q
pnpm --dir apps/web test
```
