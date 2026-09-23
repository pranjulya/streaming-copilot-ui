// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import type {
  ConversationClient,
  ConversationSnapshot,
  Message,
} from "../../features/chat/api/client";
import { Transcript } from "../../features/chat/components/Transcript";

afterEach(cleanup);

const CONVERSATION_ID = "0195f4da-0000-7000-8000-000000000001";

function snapshotWith(assistantText: string | null): ConversationSnapshot {
  const messages: Message[] = [
    {
      id: "0195f4db-0000-7000-8000-000000000001",
      conversation_id: CONVERSATION_ID,
      role: "user",
      content: "Explain backpressure",
      status: "complete",
      client_message_id: "0195f4d8-4ee0-7a35-8bc4-63cb5966b448",
      in_reply_to_id: null,
      version: 1,
      is_visible: true,
      created_at: "2026-09-09T10:29:00.000Z",
    },
  ];
  if (assistantText !== null) {
    messages.push({
      id: "0195f4db-0000-7000-8000-000000000002",
      conversation_id: CONVERSATION_ID,
      role: "assistant",
      content: assistantText,
      status: "complete",
      client_message_id: null,
      in_reply_to_id: "0195f4db-0000-7000-8000-000000000001",
      version: 1,
      is_visible: true,
      created_at: "2026-09-09T10:29:05.000Z",
    });
  }
  return {
    conversation: {
      id: CONVERSATION_ID,
      title: "Explain backpressure",
      created_at: "2026-09-09T10:29:00.000Z",
      updated_at: "2026-09-09T10:30:00.000Z",
      archived_at: null,
      active_run_id: null,
    },
    messages: { items: messages, next_cursor: null },
    active_run: null,
  };
}

function envelope(
  sequence: number,
  type: string,
  data: Record<string, unknown>,
) {
  return JSON.stringify({
    protocol_version: "1.0",
    sequence,
    event_id: `0195f4db-2159-7d06-8895-1c0f36c7d8a${sequence}`,
    type,
    occurred_at: "2026-09-09T10:30:12.481Z",
    conversation_id: CONVERSATION_ID,
    run_id: "0195f4da-0000-7000-8000-0000000000aa",
    data,
  });
}

function streamingBody(
  lines: string[],
  chunkSize = 64,
): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  const bytes = encoder.encode(lines.join("\n") + "\n");
  return new ReadableStream<Uint8Array>({
    async start(controller) {
      for (let offset = 0; offset < bytes.length; offset += chunkSize) {
        controller.enqueue(bytes.slice(offset, offset + chunkSize));
        await new Promise((resolve) => setTimeout(resolve, 10));
      }
      controller.close();
    },
  });
}

describe("Transcript streaming", () => {
  test("streams split chunks into the live bubble then shows canonical text", async () => {
    let call = 0;
    const client = {
      getConversation: vi.fn().mockImplementation(() => {
        call += 1;
        return Promise.resolve(
          snapshotWith(call > 1 ? "Backpressure is flow control." : null),
        );
      }),
    } as unknown as ConversationClient;

    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(
        streamingBody([
          envelope(1, "response.started", {
            user_message_id: "u1",
            assistant_message_id: "a1",
            client_message_id: "client-1",
            attempt: 1,
          }),
          envelope(2, "message.delta", { delta: "Back", content_index: 0 }),
          envelope(3, "message.delta", { delta: "pressure", content_index: 4 }),
          envelope(4, "message.completed", {
            message_id: "a1",
            content: "Backpressure",
            finish_reason: "stop",
          }),
          envelope(5, "response.completed", { finish_reason: "stop" }),
        ]),
        { status: 200, headers: { "content-type": "application/x-ndjson" } },
      ),
    );
    vi.stubGlobal("fetch", fetchImpl);

    render(<Transcript client={client} conversationId={CONVERSATION_ID} />);
    await screen.findByRole("heading", { name: "Explain backpressure" });
    await userEvent.type(
      screen.getByLabelText("Message"),
      "Explain backpressure{Enter}",
    );

    expect(
      await screen.findByText("Backpressure", {}, { timeout: 4000 }),
    ).toBeTruthy();
    await waitFor(
      () =>
        expect(screen.getByText("Backpressure is flow control.")).toBeTruthy(),
      { timeout: 4000 },
    );

    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`/v1/conversations/${CONVERSATION_ID}/responses`);
    const headers = init.headers as Record<string, string>;
    expect(headers["Idempotency-Key"]).toMatch(/[0-9a-f-]{36}/);
    const body = JSON.parse(String(init.body)) as {
      client_message_id: string;
      content: string;
    };
    expect(body.client_message_id).toMatch(/[0-9a-f-]{36}/);
    expect(body.content).toBe("Explain backpressure");
    vi.unstubAllGlobals();
  });

  test("reports a rejected send as a notice", async () => {
    const client = {
      getConversation: vi.fn().mockResolvedValue(snapshotWith(null)),
    } as unknown as ConversationClient;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            type: "https://copilot.local/problems/conversation_busy",
            title: "Conversation already has an active response",
            status: 409,
            code: "conversation_busy",
          }),
          {
            status: 409,
            headers: { "content-type": "application/problem+json" },
          },
        ),
      ),
    );
    render(<Transcript client={client} conversationId={CONVERSATION_ID} />);
    await screen.findByRole("heading", { name: "Explain backpressure" });
    await userEvent.type(screen.getByLabelText("Message"), "again{Enter}");
    expect(await screen.findByText(/conversation_busy/)).toBeTruthy();
    vi.unstubAllGlobals();
  });
});
