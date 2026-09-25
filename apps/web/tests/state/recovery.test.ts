import { describe, expect, test, vi } from "vitest";

import type {
  ConversationClient,
  RunSnapshot,
} from "../../features/chat/api/client";
import {
  busyActiveRunId,
  followActiveRun,
  isNetworkFailure,
  isUserAbort,
  pollRunUntilTerminal,
  supportsStreaming,
  terminalStatus,
} from "../../features/chat/state/recovery";

function run(status: RunSnapshot["status"], id = "run-1"): RunSnapshot {
  return {
    id,
    conversation_id: "c1",
    user_message_id: "u1",
    assistant_message_id: "a1",
    status,
    attempt: 1,
    last_sequence: 4,
    cancel_requested_at: null,
    error_code: null,
    diagnostic_id: null,
    partial_content: "partial",
    created_at: "2026-09-09T10:30:00.000Z",
    completed_at: null,
  };
}

describe("recovery helpers", () => {
  test("classifies network failures, aborts and client errors", async () => {
    const { ClientError } = await import("../../features/chat/api/client");
    expect(isNetworkFailure(new TypeError("failed to fetch"))).toBe(true);
    expect(
      isNetworkFailure(new ClientError(409, "conversation_busy", "busy", null)),
    ).toBe(false);
    const abort = new Error("aborted");
    abort.name = "AbortError";
    expect(isNetworkFailure(abort)).toBe(false);
    expect(isUserAbort(abort)).toBe(true);
  });

  test("busyActiveRunId extracts the active run from problem extensions", async () => {
    const { ClientError } = await import("../../features/chat/api/client");
    const error = new ClientError(409, "conversation_busy", "busy", null, {
      active_run_id: "run-9",
      conversation_id: "c1",
    });
    expect(busyActiveRunId(error)).toBe("run-9");
    expect(
      busyActiveRunId(new ClientError(409, "invalid_run_state", "no", null)),
    ).toBeNull();
  });

  test("pollRunUntilTerminal stops at a terminal status", async () => {
    const statuses: RunSnapshot["status"][] = [
      "queued",
      "streaming",
      "completed",
    ];
    let index = 0;
    const client = {
      getRun: vi.fn().mockImplementation(() => {
        const status = statuses[Math.min(index, statuses.length - 1)];
        index += 1;
        return Promise.resolve(run(status));
      }),
    } as unknown as ConversationClient;
    const result = await pollRunUntilTerminal(client, "run-1", { delayMs: 1 });
    expect(result?.status).toBe("completed");
    expect(client.getRun).toHaveBeenCalledTimes(3);
  });

  test("pollRunUntilTerminal gives up after the attempt budget", async () => {
    const client = {
      getRun: vi.fn().mockResolvedValue(run("streaming")),
    } as unknown as ConversationClient;
    const result = await pollRunUntilTerminal(client, "run-1", {
      delayMs: 1,
      attempts: 2,
    });
    expect(result).toBeNull();
  });

  test("followActiveRun posts the cursor and dispatches parsed events", async () => {
    const encoder = new TextEncoder();
    const lines = [
      JSON.stringify({
        protocol_version: "1.0",
        sequence: 5,
        event_id: "e5",
        type: "message.delta",
        occurred_at: "2026-09-09T10:30:12.481Z",
        conversation_id: "c1",
        run_id: "run-1",
        data: { delta: "more", content_index: 7 },
      }),
    ].join("\n");
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(
        new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(encoder.encode(lines + "\n"));
            controller.close();
          },
        }),
        { status: 200, headers: { "content-type": "application/x-ndjson" } },
      ),
    );
    const results: unknown[] = [];
    await followActiveRun({
      runId: "run-1",
      afterSequence: 4,
      fetchImpl,
      signal: new AbortController().signal,
      onResult: (result) => results.push(result),
    });
    expect(results).toHaveLength(1);
    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/response-runs/run-1/stream");
    expect(JSON.parse(String(init.body))).toEqual({ after_sequence: 4 });
    expect(
      (init.headers as Record<string, string>)["Idempotency-Key"],
    ).toBeUndefined();
  });

  test("terminalStatus knows the terminal set", () => {
    expect(terminalStatus("completed")).toBe(true);
    expect(terminalStatus("cancelled")).toBe(true);
    expect(terminalStatus("failed")).toBe(true);
    expect(terminalStatus("streaming")).toBe(false);
  });

  test("supportsStreaming reflects the runtime", () => {
    expect(supportsStreaming()).toBe(true);
  });

  test("streamTurn is incomplete when the NDJSON body ends without a terminal event", async () => {
    const { streamTurn } = await import("../../features/chat/state/recovery");
    const encoder = new TextEncoder();
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(
        encoder.encode(
          `${JSON.stringify({
            protocol_version: "1.0",
            sequence: 1,
            event_id: "e1",
            type: "response.started",
            occurred_at: "2026-09-09T10:30:12.481Z",
            conversation_id: "c1",
            run_id: "run-1",
            data: { attempt: 1 },
          })}\n`,
        ),
        { status: 200, headers: { "content-type": "application/x-ndjson" } },
      ),
    );
    const result = await streamTurn({
      client: {} as ConversationClient,
      turn: { kind: "create", conversationId: "c1", content: "hi" },
      clientMessageId: "cmid",
      idempotencyKey: "key",
      fetchImpl,
      signal: new AbortController().signal,
      onResult: () => {},
    });
    expect(result.outcome).toBe("incomplete");
    if (result.outcome === "incomplete") {
      expect(result.runId).toBe("run-1");
    }
  });

  test("streamTurn treats user abort as aborted, not rejected", async () => {
    const { streamTurn } = await import("../../features/chat/state/recovery");
    const abort = new Error("aborted");
    abort.name = "AbortError";
    const fetchImpl = vi.fn().mockRejectedValue(abort);
    const result = await streamTurn({
      client: {} as ConversationClient,
      turn: { kind: "create", conversationId: "c1", content: "hi" },
      clientMessageId: "cmid",
      idempotencyKey: "key",
      fetchImpl,
      signal: new AbortController().signal,
      onResult: () => {},
    });
    expect(result.outcome).toBe("aborted");
  });
});
