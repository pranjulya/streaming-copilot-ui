import { describe, expect, test } from "vitest";

import { parseNdjson } from "../../features/chat/stream/parseNdjson";

const encoder = new TextEncoder();

function envelope(
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    protocol_version: "1.0",
    sequence: 1,
    event_id: "0195f4db-2159-7d06-8895-1c0f36c7d8a4",
    type: "message.delta",
    occurred_at: "2026-09-09T10:30:12.481Z",
    conversation_id: "0195f4d4-0000-7000-8000-000000000001",
    run_id: "0195f4da-0000-7000-8000-000000000001",
    data: { message_id: "m", delta: "Backpressure is", content_index: 0 },
    ...overrides,
  };
}

function streamFrom(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
  });
}

async function collect(
  chunks: Uint8Array[],
  signal = new AbortController().signal,
) {
  const results = [];
  for await (const result of parseNdjson(streamFrom(chunks), signal)) {
    results.push(result);
  }
  return results;
}

describe("parseNdjson", () => {
  test("parses an event split across three chunks", async () => {
    const line = `${JSON.stringify(envelope())}\n`;
    const bytes = encoder.encode(line);
    const results = await collect([
      bytes.slice(0, 10),
      bytes.slice(10, 40),
      bytes.slice(40),
    ]);
    expect(results).toHaveLength(1);
    expect(results[0]).toMatchObject({ kind: "event" });
  });

  test("parses two events delivered in one chunk", async () => {
    const lines =
      JSON.stringify(envelope()) +
      "\n" +
      JSON.stringify(envelope({ sequence: 2 })) +
      "\n";
    const results = await collect([encoder.encode(lines)]);
    expect(results).toHaveLength(2);
    expect(results.map((result) => result.kind)).toEqual(["event", "event"]);
  });

  test("handles a multibyte character split across chunks", async () => {
    const line = `${JSON.stringify(envelope({ data: { delta: "café" } }))}\n`;
    const bytes = encoder.encode(line);
    const splitAt = bytes.indexOf(0xc3) + 1;
    const results = await collect([
      bytes.slice(0, splitAt),
      bytes.slice(splitAt),
    ]);
    expect(results[0]).toMatchObject({ kind: "event" });
    if (results[0].kind === "event") {
      expect(results[0].event.data.delta).toBe("café");
    }
  });

  test("keeps supplementary-plane characters intact for content_index math", async () => {
    const delta = "Backpressure 👍 is";
    const results = await collect([
      encoder.encode(
        `${JSON.stringify(envelope({ data: { delta, content_index: 0 } }))}\n`,
      ),
    ]);
    if (results[0].kind !== "event") throw new Error("expected an event");
    const received = String(results[0].event.data.delta);
    expect(Array.from(received).length).toBe(17);
    expect(received).toBe(delta);
  });

  test("tolerates CRLF line endings and ignores empty lines", async () => {
    const body =
      JSON.stringify(envelope()) +
      "\r\n" +
      "\r\n" +
      JSON.stringify(envelope({ sequence: 2 })) +
      "\n";
    const results = await collect([encoder.encode(body)]);
    expect(results).toHaveLength(2);
  });

  test("yields invalid for malformed JSON and missing fields", async () => {
    const results = await collect([
      encoder.encode("{not json}\n"),
      encoder.encode(JSON.stringify({ sequence: 1 }) + "\n"),
    ]);
    expect(results.map((result) => result.kind)).toEqual([
      "invalid",
      "invalid",
    ]);
  });

  test("rejects a non-integer sequence and an array data payload", async () => {
    const results = await collect([
      encoder.encode(`${JSON.stringify(envelope({ sequence: 1.5 }))}\n`),
      encoder.encode(`${JSON.stringify(envelope({ data: [] }))}\n`),
    ]);
    expect(results.map((result) => result.kind)).toEqual([
      "invalid",
      "invalid",
    ]);
  });

  test("yields protocol for an unsupported major version", async () => {
    const results = await collect([
      encoder.encode(
        `${JSON.stringify(envelope({ protocol_version: "2.0" }))}\n`,
      ),
    ]);
    expect(results[0]).toMatchObject({ kind: "protocol" });
  });

  test("stops after an unsupported major version", async () => {
    const body =
      JSON.stringify(envelope({ protocol_version: "2.0" })) +
      "\n" +
      JSON.stringify(envelope({ sequence: 2 })) +
      "\n";
    const results = await collect([encoder.encode(body)]);
    expect(results).toHaveLength(1);
    expect(results[0]).toMatchObject({ kind: "protocol" });
  });

  test("yields unknown event types for the reducer to ignore", async () => {
    const results = await collect([
      encoder.encode(`${JSON.stringify(envelope({ type: "tool.started" }))}\n`),
    ]);
    expect(results[0]).toMatchObject({ kind: "event" });
    if (results[0].kind === "event") {
      expect(results[0].event.type).toBe("tool.started");
    }
  });

  test("aborting stops iteration and releases the reader", async () => {
    const controller = new AbortController();
    const stream = new ReadableStream<Uint8Array>({
      start(inner) {
        inner.enqueue(encoder.encode(`${JSON.stringify(envelope())}\n`));
      },
      cancel() {
        (stream as unknown as { cancelled: boolean }).cancelled = true;
      },
    });
    const results = [];
    for await (const result of parseNdjson(stream, controller.signal)) {
      results.push(result);
      controller.abort();
    }
    expect(results).toHaveLength(1);
    expect((stream as unknown as { cancelled?: boolean }).cancelled).toBe(true);
  });
});
