import { describe, expect, test, vi } from "vitest";
import {
  ClientError,
  ConversationClient,
  newIdempotencyKey,
} from "../features/chat/api/client";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function problemResponse(
  status: number,
  code: string,
  title: string,
): Response {
  return new Response(
    JSON.stringify({
      type: `https://copilot.local/problems/${code}`,
      title,
      status,
      code,
      diagnostic_id: "0195f4db-2159-7d06-8895-1c0f36c7d8a4",
    }),
    { status, headers: { "content-type": "application/problem+json" } },
  );
}

describe("ConversationClient", () => {
  test("maps problem responses to ClientError with status and code", async () => {
    const cases: Array<[number, string]> = [
      [401, "unauthenticated"],
      [404, "not_found"],
      [409, "conversation_busy"],
      [429, "rate_limited"],
    ];
    for (const [status, code] of cases) {
      const fetchImpl = vi
        .fn()
        .mockResolvedValue(problemResponse(status, code, "nope"));
      const client = new ConversationClient({ fetchImpl });
      await expect(
        client.getConversation("0195f4da-0000-7000-8000-000000000000"),
      ).rejects.toMatchObject({
        name: "ClientError",
        status,
        code,
      });
    }
  });

  test("client error keeps the diagnostic id", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(problemResponse(500, "internal_error", "boom"));
    const client = new ConversationClient({ fetchImpl });
    const error = await client.listConversations().catch((caught) => caught);
    expect(error).toBeInstanceOf(ClientError);
    expect((error as ClientError).diagnosticId).toBe(
      "0195f4db-2159-7d06-8895-1c0f36c7d8a4",
    );
  });

  test("classifies kind and retryability from the problem catalog", async () => {
    const cases: Array<[number, string, string, boolean]> = [
      [400, "validation_failed", "validation", false],
      [401, "unauthenticated", "authentication", false],
      [404, "not_found", "not_found", false],
      [409, "conversation_busy", "conflict", false],
      [413, "payload_too_large", "payload_too_large", false],
      [429, "rate_limited", "rate_limited", true],
      [500, "internal_error", "server", true],
      [503, "service_unavailable", "unavailable", true],
    ];
    for (const [status, code, kind, retryable] of cases) {
      const fetchImpl = vi
        .fn()
        .mockResolvedValue(problemResponse(status, code, "x"));
      const error = await new ConversationClient({ fetchImpl })
        .listConversations()
        .catch((caught) => caught);
      expect(error).toBeInstanceOf(ClientError);
      expect((error as ClientError).kind).toBe(kind);
      expect((error as ClientError).retryable).toBe(retryable);
    }
  });

  test("treats a transport failure as a retryable network error", async () => {
    const fetchImpl = vi
      .fn()
      .mockRejectedValue(new TypeError("Failed to fetch"));
    const error = await new ConversationClient({ fetchImpl })
      .listConversations()
      .catch((caught) => caught);
    expect(error).toBeInstanceOf(ClientError);
    expect((error as ClientError).status).toBe(0);
    expect((error as ClientError).kind).toBe("network");
    expect((error as ClientError).retryable).toBe(true);
  });

  test("preserves an abort instead of reclassifying it", async () => {
    const abort = new Error("aborted");
    abort.name = "AbortError";
    const fetchImpl = vi.fn().mockRejectedValue(abort);
    const error = await new ConversationClient({ fetchImpl })
      .listConversations()
      .catch((caught) => caught);
    expect(error).toBe(abort);
  });

  test("list passes cursor, limit and include_archived", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, { items: [], next_cursor: null }));
    const client = new ConversationClient({ fetchImpl });
    await client.listConversations({
      cursor: "abc",
      limit: 5,
      includeArchived: true,
    });
    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      "/v1/conversations?cursor=abc&limit=5&include_archived=true",
    );
    expect(init.method).toBe("GET");
  });

  test("create sends an idempotency key and returns the conversation", async () => {
    const conversation = {
      id: "0195f4da-0000-7000-8000-000000000000",
      title: "New conversation",
      created_at: "2026-09-09T10:29:00.000Z",
      updated_at: "2026-09-09T10:29:00.000Z",
      archived_at: null,
      active_run_id: null,
    };
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse(201, conversation));
    const client = new ConversationClient({ fetchImpl });
    const key = newIdempotencyKey();
    const result = await client.createConversation(undefined, {
      idempotencyKey: key,
    });
    expect(result.title).toBe("New conversation");
    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/conversations");
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["Idempotency-Key"]).toBe(
      key,
    );
    expect(init.body).toBe("{}");
  });

  test("patch sends archived changes with a fresh key by default", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse(200, {
        id: "0195f4da-0000-7000-8000-000000000000",
        title: "t",
        created_at: "2026-09-09T10:29:00.000Z",
        updated_at: "2026-09-09T10:29:00.000Z",
        archived_at: "2026-09-09T10:30:00.000Z",
        active_run_id: null,
      }),
    );
    const client = new ConversationClient({ fetchImpl });
    await client.patchConversation("0195f4da-0000-7000-8000-000000000000", {
      archived: true,
    });
    const [, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(String(init.body))).toEqual({ archived: true });
    expect((init.headers as Record<string, string>)["Idempotency-Key"]).toMatch(
      /[0-9a-f-]{36}/,
    );
  });

  test("getConversation returns the snapshot envelope", async () => {
    const snapshot = {
      conversation: {
        id: "0195f4da-0000-7000-8000-000000000000",
        title: "t",
        created_at: "2026-09-09T10:29:00.000Z",
        updated_at: "2026-09-09T10:29:00.000Z",
        archived_at: null,
        active_run_id: null,
      },
      messages: { items: [], next_cursor: null },
      active_run: null,
    };
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, snapshot));
    const client = new ConversationClient({ fetchImpl });
    const result = await client.getConversation(
      "0195f4da-0000-7000-8000-000000000000",
    );
    expect(result.messages.items).toEqual([]);
    expect(result.active_run).toBeNull();
  });
});
