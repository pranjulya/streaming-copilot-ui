// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";

import type {
  ConversationClient,
  ConversationSnapshot,
  Message,
} from "../../features/chat/api/client";
import { StatusText } from "../../features/chat/components/StatusText";
import { Transcript } from "../../features/chat/components/Transcript";

afterEach(cleanup);

function message(overrides: Partial<Message> = {}): Message {
  return {
    id: "0195f4db-0000-7000-8000-000000000001",
    conversation_id: "0195f4da-0000-7000-8000-000000000001",
    role: "user",
    content: "Hello there",
    status: "complete",
    client_message_id: "0195f4d8-4ee0-7a35-8bc4-63cb5966b448",
    in_reply_to_id: null,
    version: 1,
    is_visible: true,
    created_at: "2026-09-09T10:29:00.000Z",
    ...overrides,
  };
}

function snapshot(
  overrides: Partial<ConversationSnapshot> = {},
): ConversationSnapshot {
  return {
    conversation: {
      id: "0195f4da-0000-7000-8000-000000000001",
      title: "Explain backpressure",
      created_at: "2026-09-09T10:29:00.000Z",
      updated_at: "2026-09-09T10:30:00.000Z",
      archived_at: null,
      active_run_id: null,
    },
    messages: { items: [], next_cursor: null },
    active_run: null,
    ...overrides,
  };
}

function stubClient(result: ConversationSnapshot): ConversationClient {
  return {
    getConversation: vi.fn().mockResolvedValue(result),
  } as unknown as ConversationClient;
}

describe("Transcript", () => {
  test("renders visible messages oldest-first in a semantic list", async () => {
    const items = [
      message(),
      message({
        id: "0195f4db-0000-7000-8000-000000000002",
        role: "assistant",
        content: "An answer",
        in_reply_to_id: "0195f4db-0000-7000-8000-000000000001",
      }),
      message({
        id: "0195f4db-0000-7000-8000-000000000003",
        role: "assistant",
        content: "hidden old version",
        is_visible: false,
        in_reply_to_id: "0195f4db-0000-7000-8000-000000000001",
      }),
    ];
    render(
      <Transcript
        client={stubClient(
          snapshot({ messages: { items, next_cursor: null } }),
        )}
        conversationId="0195f4da-0000-7000-8000-000000000001"
      />,
    );
    expect(
      await screen.findByRole("heading", { name: "Explain backpressure" }),
    ).toBeTruthy();
    const list = screen.getByRole("list");
    const texts = Array.from(list.querySelectorAll(".message-text")).map(
      (node) => node.textContent,
    );
    expect(texts).toEqual(["Hello there", "An answer"]);
  });

  test("shows a loading status before data arrives", () => {
    const client = {
      getConversation: vi.fn().mockReturnValue(new Promise(() => {})),
    } as unknown as ConversationClient;
    render(<Transcript client={client} conversationId="x" />);
    expect(screen.getByRole("status").textContent).toContain(
      "Loading conversation",
    );
  });

  test("follows message next_cursor until later pages are loaded", async () => {
    const older = message({ id: "msg-old", content: "oldest turn" });
    const newer = message({
      id: "msg-new",
      content: "newest turn",
      created_at: "2026-09-09T11:00:00.000Z",
    });
    const getConversation = vi
      .fn()
      .mockResolvedValueOnce(
        snapshot({ messages: { items: [older], next_cursor: "cursor-1" } }),
      )
      .mockResolvedValueOnce(
        snapshot({ messages: { items: [newer], next_cursor: null } }),
      );
    const client = { getConversation } as unknown as ConversationClient;
    render(
      <Transcript
        client={client}
        conversationId="0195f4da-0000-7000-8000-000000000001"
      />,
    );
    expect(await screen.findByText("oldest turn")).toBeTruthy();
    expect(screen.getByText("newest turn")).toBeTruthy();
    expect(getConversation).toHaveBeenCalledTimes(2);
    expect(getConversation.mock.calls[1][1]).toMatchObject({
      cursor: "cursor-1",
    });
  });

  test("shows a not-found summary for 404", async () => {
    const { ClientError } = await import("../../features/chat/api/client");
    const client = {
      getConversation: vi
        .fn()
        .mockRejectedValue(new ClientError(404, "not_found", "nope", null)),
    } as unknown as ConversationClient;
    render(<Transcript client={client} conversationId="x" />);
    expect(await screen.findByRole("alert")).toBeTruthy();
  });

  test("exposes generation status through a polite status region", async () => {
    const run = {
      id: "0195f4dc-0000-7000-8000-000000000001",
      conversation_id: "0195f4da-0000-7000-8000-000000000001",
      user_message_id: "0195f4db-0000-7000-8000-000000000001",
      assistant_message_id: "0195f4db-0000-7000-8000-000000000002",
      status: "streaming" as const,
      attempt: 1,
      last_sequence: 4,
      cancel_requested_at: null,
      error_code: null,
      diagnostic_id: null,
      partial_content: "Backpressure is",
      created_at: "2026-09-09T10:30:00.000Z",
      completed_at: null,
    };
    render(
      <Transcript
        client={stubClient(snapshot({ active_run: run }))}
        conversationId="0195f4da-0000-7000-8000-000000000001"
      />,
    );
    expect(await screen.findByText("Generating a response…")).toBeTruthy();
  });
});

describe("StatusText", () => {
  test("renders nothing for null status but keeps the status role", () => {
    render(<StatusText status={null} />);
    expect(screen.getByRole("status").textContent).toBe("");
  });
});
