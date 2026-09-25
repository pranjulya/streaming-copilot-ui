import { describe, expect, test } from "vitest";

import type { StreamEvent } from "../../features/chat/stream/parseNdjson";
import {
  chatReducer,
  emptyTurn,
  initialChatState,
  type ChatAction,
  type ChatState,
} from "../../features/chat/state/chatReducer";

const CONVERSATION = "0195f4d4-0000-7000-8000-000000000001";

function event(overrides: Partial<StreamEvent> = {}): StreamEvent {
  return {
    protocol_version: "1.0",
    sequence: 1,
    event_id: "0195f4db-2159-7d06-8895-1c0f36c7d8a4",
    type: "message.delta",
    occurred_at: "2026-09-09T10:30:12.481Z",
    conversation_id: CONVERSATION,
    run_id: "0195f4da-0000-7000-8000-000000000001",
    data: {},
    ...overrides,
  };
}

function reduce(
  actions: ChatAction[],
  from: ChatState = initialChatState,
): ChatState {
  return actions.reduce(chatReducer, from);
}

function started(sequence = 1): StreamEvent {
  return event({
    sequence,
    type: "response.started",
    data: {
      user_message_id: "user-1",
      assistant_message_id: "assistant-1",
      client_message_id: "client-1",
      attempt: 1,
    },
  });
}

function delta(sequence: number, text: string, index: number): StreamEvent {
  return event({
    sequence,
    type: "message.delta",
    data: { delta: text, content_index: index },
  });
}

describe("chatReducer", () => {
  test("optimistic turn then response.started maps ids", () => {
    const state = reduce([
      {
        type: "optimistic",
        conversationId: CONVERSATION,
        clientMessageId: "client-1",
        content: "hi",
      },
      { type: "event", conversationId: CONVERSATION, event: started() },
    ]);
    const turn = state.turnsByConversation[CONVERSATION];
    expect(turn.status).toBe("streaming");
    expect(turn.clientMessageId).toBe("client-1");
    expect(turn.userMessageId).toBe("user-1");
    expect(turn.assistantMessageId).toBe("assistant-1");
    expect(turn.runId).toBe("0195f4da-0000-7000-8000-000000000001");
    expect(turn.userContent).toBe("hi");
  });

  test("deltas append in order and drive status to completed", () => {
    const state = reduce([
      {
        type: "optimistic",
        conversationId: CONVERSATION,
        clientMessageId: "client-1",
        content: "q",
      },
      { type: "event", conversationId: CONVERSATION, event: started() },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: delta(2, "Back", 0),
      },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: delta(3, "pressure", 4),
      },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: event({
          sequence: 4,
          type: "response.completed",
          data: { finish_reason: "stop" },
        }),
      },
    ]);
    const turn = state.turnsByConversation[CONVERSATION];
    expect(turn.assistantContent).toBe("Backpressure");
    expect(turn.status).toBe("completed");
    expect(turn.lastSequence).toBe(4);
  });

  test("duplicate sequence numbers are ignored", () => {
    const state = reduce([
      {
        type: "optimistic",
        conversationId: CONVERSATION,
        clientMessageId: "client-1",
        content: "q",
      },
      { type: "event", conversationId: CONVERSATION, event: started() },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: delta(2, "once", 0),
      },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: delta(2, "twice", 0),
      },
    ]);
    expect(state.turnsByConversation[CONVERSATION].assistantContent).toBe(
      "once",
    );
  });

  test("a sequence gap marks reconciling without appending", () => {
    const state = reduce([
      {
        type: "optimistic",
        conversationId: CONVERSATION,
        clientMessageId: "client-1",
        content: "q",
      },
      { type: "event", conversationId: CONVERSATION, event: started() },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: delta(4, "lost text", 0),
      },
    ]);
    const turn = state.turnsByConversation[CONVERSATION];
    expect(turn.status).toBe("reconciling");
    expect(turn.assistantContent).toBe("");
  });

  test("content_index mismatch marks reconciling without appending", () => {
    const state = reduce([
      {
        type: "optimistic",
        conversationId: CONVERSATION,
        clientMessageId: "client-1",
        content: "q",
      },
      { type: "event", conversationId: CONVERSATION, event: started() },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: delta(2, "abc", 5),
      },
    ]);
    const turn = state.turnsByConversation[CONVERSATION];
    expect(turn.status).toBe("reconciling");
    expect(turn.assistantContent).toBe("");
    expect(turn.lastSequence).toBe(2);
  });

  test("message.completed still applies after a content_index mismatch", () => {
    const state = reduce([
      {
        type: "optimistic",
        conversationId: CONVERSATION,
        clientMessageId: "client-1",
        content: "q",
      },
      { type: "event", conversationId: CONVERSATION, event: started() },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: delta(2, "abc", 5),
      },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: event({
          sequence: 3,
          type: "message.completed",
          data: {
            message_id: "assistant-1",
            content: "canonical",
            finish_reason: "stop",
          },
        }),
      },
    ]);
    expect(state.turnsByConversation[CONVERSATION].assistantContent).toBe(
      "canonical",
    );
    expect(state.turnsByConversation[CONVERSATION].status).toBe("reconciling");
  });

  test("snapshot copies ids without String(null)", () => {
    const state = reduce([
      {
        type: "optimistic",
        conversationId: CONVERSATION,
        clientMessageId: "client-1",
        content: "q",
      },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: event({
          sequence: 3,
          type: "response.snapshot",
          data: {
            status: "streaming",
            content: "so far",
            last_sequence: 3,
            user_message_id: "user-1",
            assistant_message_id: "assistant-1",
            client_message_id: "client-1",
          },
        }),
      },
    ]);
    const turn = state.turnsByConversation[CONVERSATION];
    expect(turn.userMessageId).toBe("user-1");
    expect(turn.assistantMessageId).toBe("assistant-1");
    expect(turn.clientMessageId).toBe("client-1");
    expect(turn.userMessageId).not.toBe("null");
  });

  test("response.started missing ids keep prior values", () => {
    const state = reduce([
      {
        type: "optimistic",
        conversationId: CONVERSATION,
        clientMessageId: "client-1",
        content: "q",
      },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: event({
          sequence: 1,
          type: "response.started",
          data: { attempt: 1 },
        }),
      },
    ]);
    const turn = state.turnsByConversation[CONVERSATION];
    expect(turn.clientMessageId).toBe("client-1");
    expect(turn.userMessageId).toBeNull();
    expect(turn.assistantMessageId).toBeNull();
  });

  test("canonical-status does not overwrite completed", () => {
    const state = reduce([
      {
        type: "optimistic",
        conversationId: CONVERSATION,
        clientMessageId: "client-1",
        content: "q",
      },
      { type: "event", conversationId: CONVERSATION, event: started() },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: event({
          sequence: 2,
          type: "response.completed",
          data: { finish_reason: "stop" },
        }),
      },
      {
        type: "canonical-status",
        conversationId: CONVERSATION,
        status: "cancelled",
      },
    ]);
    expect(state.turnsByConversation[CONVERSATION].status).toBe("completed");
  });

  test("response.cancelled does not overwrite completed", () => {
    const state = reduce([
      {
        type: "optimistic",
        conversationId: CONVERSATION,
        clientMessageId: "client-1",
        content: "q",
      },
      { type: "event", conversationId: CONVERSATION, event: started() },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: event({
          sequence: 2,
          type: "response.completed",
          data: { finish_reason: "stop" },
        }),
      },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: event({
          sequence: 3,
          type: "response.cancelled",
          data: { reason: "user_requested" },
        }),
      },
    ]);
    expect(state.turnsByConversation[CONVERSATION].status).toBe("completed");
  });

  test("sendFailed clears the optimistic turn", () => {
    const state = reduce([
      {
        type: "optimistic",
        conversationId: CONVERSATION,
        clientMessageId: "client-1",
        content: "q",
      },
      { type: "sendFailed", conversationId: CONVERSATION },
    ]);
    expect(state.turnsByConversation[CONVERSATION]).toEqual(emptyTurn());
  });

  test("message.completed replaces accumulated content", () => {
    const state = reduce([
      {
        type: "optimistic",
        conversationId: CONVERSATION,
        clientMessageId: "client-1",
        content: "q",
      },
      { type: "event", conversationId: CONVERSATION, event: started() },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: delta(2, "partial", 0),
      },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: event({
          sequence: 3,
          type: "message.completed",
          data: {
            message_id: "assistant-1",
            content: "partial canonical answer",
            finish_reason: "stop",
          },
        }),
      },
    ]);
    expect(state.turnsByConversation[CONVERSATION].assistantContent).toBe(
      "partial canonical answer",
    );
  });

  test("response.snapshot replaces content and cursor", () => {
    const state = reduce([
      {
        type: "optimistic",
        conversationId: CONVERSATION,
        clientMessageId: "client-1",
        content: "q",
      },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: event({
          sequence: 42,
          type: "response.snapshot",
          data: {
            status: "streaming",
            content: "canonical so far",
            last_sequence: 42,
          },
        }),
      },
    ]);
    const turn = state.turnsByConversation[CONVERSATION];
    expect(turn.assistantContent).toBe("canonical so far");
    expect(turn.lastSequence).toBe(42);
    expect(turn.status).toBe("streaming");
  });

  test("heartbeats do not change state and unknown persisted types advance the cursor", () => {
    const before = reduce([
      {
        type: "optimistic",
        conversationId: CONVERSATION,
        clientMessageId: "client-1",
        content: "q",
      },
      { type: "event", conversationId: CONVERSATION, event: started() },
    ]);
    const afterHeartbeat = reduce(
      [
        {
          type: "event",
          conversationId: CONVERSATION,
          event: event({
            sequence: 2,
            type: "heartbeat",
            data: { last_sequence: 1 },
          }),
        },
      ],
      before,
    );
    expect(afterHeartbeat).toEqual(before);

    const afterUnknown = reduce(
      [
        {
          type: "event",
          conversationId: CONVERSATION,
          event: event({ sequence: 2, type: "tool.started" }),
        },
      ],
      before,
    );
    const turn = afterUnknown.turnsByConversation[CONVERSATION];
    expect(turn.lastSequence).toBe(2);
    expect(turn.status).toBe("streaming");
    expect(turn.assistantContent).toBe("");
  });

  test("ignores events from a different run", () => {
    const state = reduce([
      {
        type: "optimistic",
        conversationId: CONVERSATION,
        clientMessageId: "client-1",
        content: "q",
      },
      { type: "event", conversationId: CONVERSATION, event: started() },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: event({
          sequence: 2,
          run_id: "0195f4da-0000-7000-8000-0000000000ff",
          type: "message.delta",
          data: { delta: "leak", content_index: 0 },
        }),
      },
    ]);
    const turn = state.turnsByConversation[CONVERSATION];
    expect(turn.assistantContent).toBe("");
    expect(turn.lastSequence).toBe(1);
  });

  test("a duplicate response.started does not rewind the cursor", () => {
    const state = reduce([
      {
        type: "optimistic",
        conversationId: CONVERSATION,
        clientMessageId: "client-1",
        content: "q",
      },
      { type: "event", conversationId: CONVERSATION, event: started() },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: delta(2, "Back", 0),
      },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: delta(3, "pressure", 4),
      },
      { type: "event", conversationId: CONVERSATION, event: started() },
    ]);
    const turn = state.turnsByConversation[CONVERSATION];
    expect(turn.assistantContent).toBe("Backpressure");
    expect(turn.lastSequence).toBe(3);
    expect(turn.status).toBe("streaming");
  });

  test('no id is coerced to the string "null"', () => {
    const withNullCompleted = reduce([
      {
        type: "optimistic",
        conversationId: CONVERSATION,
        clientMessageId: "client-1",
        content: "q",
      },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: event({
          sequence: 1,
          type: "response.started",
          data: { attempt: 1 },
        }),
      },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: event({
          sequence: 2,
          type: "message.completed",
          data: { message_id: null, content: "done", finish_reason: "stop" },
        }),
      },
    ]);
    expect(
      withNullCompleted.turnsByConversation[CONVERSATION].assistantMessageId,
    ).toBeNull();
    expect(
      withNullCompleted.turnsByConversation[CONVERSATION].assistantContent,
    ).toBe("done");

    const withNullDiagnostic = reduce([
      {
        type: "optimistic",
        conversationId: CONVERSATION,
        clientMessageId: "client-1",
        content: "q",
      },
      { type: "event", conversationId: CONVERSATION, event: started() },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: event({
          sequence: 2,
          type: "response.failed",
          data: {
            code: "provider_unavailable",
            message: "down",
            retryable: true,
            diagnostic_id: null,
            content: "",
          },
        }),
      },
    ]);
    const failed = withNullDiagnostic.turnsByConversation[CONVERSATION];
    expect(failed.diagnosticId).toBeNull();
    expect(failed.errorCode).toBe("provider_unavailable");
  });

  test("cancelled and failed turns keep partial content", () => {
    const cancelled = reduce([
      {
        type: "optimistic",
        conversationId: CONVERSATION,
        clientMessageId: "client-1",
        content: "q",
      },
      { type: "event", conversationId: CONVERSATION, event: started() },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: delta(2, "partial", 0),
      },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: event({
          sequence: 3,
          type: "response.cancelled",
          data: { reason: "user_requested", content: "partial" },
        }),
      },
    ]);
    expect(cancelled.turnsByConversation[CONVERSATION].status).toBe(
      "cancelled",
    );
    expect(cancelled.turnsByConversation[CONVERSATION].assistantContent).toBe(
      "partial",
    );

    const failed = reduce([
      {
        type: "optimistic",
        conversationId: CONVERSATION,
        clientMessageId: "client-1",
        content: "q",
      },
      { type: "event", conversationId: CONVERSATION, event: started() },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: event({
          sequence: 2,
          type: "response.failed",
          data: { code: "provider_unavailable", message: "down", content: "" },
        }),
      },
    ]);
    expect(failed.turnsByConversation[CONVERSATION].status).toBe("failed");
    expect(failed.turnsByConversation[CONVERSATION].errorCode).toBe(
      "provider_unavailable",
    );
  });

  test("navigating away keeps other conversations' run state", () => {
    const other = "0195f4d4-0000-7000-8000-000000000002";
    const state = reduce([
      {
        type: "optimistic",
        conversationId: CONVERSATION,
        clientMessageId: "client-1",
        content: "q",
      },
      { type: "event", conversationId: CONVERSATION, event: started() },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: delta(2, "half", 0),
      },
      { type: "navigate", conversationId: other },
    ]);
    expect(state.activeConversationId).toBe(other);
    expect(state.turnsByConversation[CONVERSATION].assistantContent).toBe(
      "half",
    );
    expect(state.turnsByConversation[CONVERSATION].status).toBe("streaming");
  });

  test("emptyTurn is a stable idle baseline", () => {
    expect(emptyTurn().status).toBe("idle");
    expect(emptyTurn()).toEqual(emptyTurn());
  });

  test("stop requested then completion wins the race shows completed", () => {
    const state = reduce([
      {
        type: "optimistic",
        conversationId: CONVERSATION,
        clientMessageId: "client-1",
        content: "q",
      },
      { type: "event", conversationId: CONVERSATION, event: started() },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: delta(2, "answ", 0),
      },
      { type: "stop-requested", conversationId: CONVERSATION },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: event({
          sequence: 3,
          type: "message.completed",
          data: { content: "answer", finish_reason: "stop" },
        }),
      },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: event({
          sequence: 4,
          type: "response.completed",
          data: { finish_reason: "stop" },
        }),
      },
    ]);
    const turn = state.turnsByConversation[CONVERSATION];
    expect(turn.status).toBe("completed");
    expect(turn.assistantContent).toBe("answer");
  });

  test("canonical-status records a run discovered during reconciliation", () => {
    const state = reduce([
      {
        type: "optimistic",
        conversationId: CONVERSATION,
        clientMessageId: "client-1",
        content: "q",
      },
      { type: "stop-requested", conversationId: CONVERSATION },
      {
        type: "canonical-status",
        conversationId: CONVERSATION,
        status: "cancelled",
        runId: "run-9",
      },
    ]);
    const turn = state.turnsByConversation[CONVERSATION];
    expect(turn.status).toBe("cancelled");
    expect(turn.runId).toBe("run-9");
  });

  test("stop requested then canonical cancelled keeps the partial text", () => {
    const state = reduce([
      {
        type: "optimistic",
        conversationId: CONVERSATION,
        clientMessageId: "client-1",
        content: "q",
      },
      { type: "event", conversationId: CONVERSATION, event: started() },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: delta(2, "half", 0),
      },
      { type: "stop-requested", conversationId: CONVERSATION },
      {
        type: "canonical-status",
        conversationId: CONVERSATION,
        status: "cancelled",
      },
    ]);
    const turn = state.turnsByConversation[CONVERSATION];
    expect(turn.status).toBe("cancelled");
    expect(turn.assistantContent).toBe("half");
  });

  test("restart-turn resets the cursor for a new run", () => {
    const state = reduce([
      {
        type: "optimistic",
        conversationId: CONVERSATION,
        clientMessageId: "client-1",
        content: "q",
      },
      { type: "event", conversationId: CONVERSATION, event: started() },
      {
        type: "event",
        conversationId: CONVERSATION,
        event: delta(2, "old", 0),
      },
      { type: "restart-turn", conversationId: CONVERSATION },
    ]);
    const turn = state.turnsByConversation[CONVERSATION];
    expect(turn.status).toBe("submitting");
    expect(turn.lastSequence).toBe(0);
    expect(turn.assistantContent).toBe("");
    expect(turn.userContent).toBe("q");
  });
});
