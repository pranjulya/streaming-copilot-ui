import type { StreamEvent } from "../stream/parseNdjson";

export type TurnStatus =
  | "idle"
  | "queued"
  | "submitting"
  | "connecting"
  | "streaming"
  | "cancelling"
  | "stopping"
  | "reconciling"
  | "completed"
  | "cancelled"
  | "failed";

export type TurnState = {
  clientMessageId: string | null;
  userMessageId: string | null;
  assistantMessageId: string | null;
  runId: string | null;
  status: TurnStatus;
  userContent: string;
  assistantContent: string;
  lastSequence: number;
  errorCode: string | null;
  diagnosticId: string | null;
};

export type ChatState = {
  activeConversationId: string | null;
  turnsByConversation: Record<string, TurnState>;
};

export type ChatAction =
  | {
      type: "optimistic";
      conversationId: string;
      clientMessageId: string;
      content: string;
    }
  | { type: "event"; conversationId: string; event: StreamEvent }
  | { type: "navigate"; conversationId: string }
  | { type: "reset"; conversationId: string }
  | { type: "sendFailed"; conversationId: string }
  | { type: "reconcile"; conversationId: string }
  | { type: "stop-requested"; conversationId: string }
  | {
      type: "canonical-status";
      conversationId: string;
      status: TurnStatus;
      content?: string;
    }
  | { type: "restart-turn"; conversationId: string };

export function emptyTurn(): TurnState {
  return {
    clientMessageId: null,
    userMessageId: null,
    assistantMessageId: null,
    runId: null,
    status: "idle",
    userContent: "",
    assistantContent: "",
    lastSequence: 0,
    errorCode: null,
    diagnosticId: null,
  };
}

export const initialChatState: ChatState = {
  activeConversationId: null,
  turnsByConversation: {},
};

function contentIndex(content: string): number {
  return Array.from(content).length;
}

function optionalString(
  value: unknown,
  fallback: string | null,
): string | null {
  return typeof value === "string" ? value : fallback;
}

function optionalNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "navigate":
      return { ...state, activeConversationId: action.conversationId };
    case "reset": {
      const turns = { ...state.turnsByConversation };
      delete turns[action.conversationId];
      return { ...state, turnsByConversation: turns };
    }
    case "optimistic": {
      return {
        ...state,
        turnsByConversation: {
          ...state.turnsByConversation,
          [action.conversationId]: {
            ...emptyTurn(),
            clientMessageId: action.clientMessageId,
            status: "submitting",
            userContent: action.content,
          },
        },
      };
    }
    case "sendFailed":
      return withTurn(state, action.conversationId, () => emptyTurn());
    case "reconcile":
      return withTurn(state, action.conversationId, (turn) => ({
        ...turn,
        status: "reconciling",
      }));
    case "stop-requested":
      return withTurn(state, action.conversationId, (turn) => ({
        ...turn,
        status: turn.status === "completed" ? turn.status : "stopping",
      }));
    case "canonical-status":
      return withTurn(state, action.conversationId, (turn) => ({
        ...turn,
        status: action.status,
        assistantContent:
          action.content === undefined ? turn.assistantContent : action.content,
      }));
    case "restart-turn":
      return withTurn(state, action.conversationId, (turn) => ({
        ...emptyTurn(),
        clientMessageId: turn.clientMessageId,
        userContent: turn.userContent,
        status: "submitting",
      }));
    case "event":
      return applyEvent(state, action.conversationId, action.event);
    default:
      return state;
  }
}

function withTurn(
  state: ChatState,
  conversationId: string,
  update: (turn: TurnState) => TurnState,
): ChatState {
  const current = state.turnsByConversation[conversationId] ?? emptyTurn();
  return {
    ...state,
    turnsByConversation: {
      ...state.turnsByConversation,
      [conversationId]: update(current),
    },
  };
}

const KNOWN_EVENT_TYPES = new Set([
  "message.delta",
  "usage.updated",
  "message.completed",
  "response.completed",
  "response.cancelled",
  "response.failed",
]);

function advance(
  turn: TurnState,
  sequence: number,
  patch: Partial<TurnState> = {},
): TurnState {
  return { ...turn, ...patch, lastSequence: sequence };
}

function applyEvent(
  state: ChatState,
  conversationId: string,
  event: StreamEvent,
): ChatState {
  if (event.type === "heartbeat") return state;
  const turn = state.turnsByConversation[conversationId] ?? emptyTurn();
  // state-machine §4: apply an event only when its run ID matches, so events
  // from another run (retry/regenerate) cannot leak into this turn.
  if (turn.runId !== null && event.run_id !== turn.runId) return state;

  if (event.type === "response.snapshot") {
    return withTurn(state, conversationId, (current) => ({
      ...current,
      status: snapshotStatus(event),
      runId: event.run_id,
      assistantContent:
        typeof event.data.content === "string"
          ? event.data.content
          : current.assistantContent,
      lastSequence: optionalNumber(
        event.data.last_sequence,
        current.lastSequence,
      ),
      userMessageId: optionalString(
        event.data.user_message_id,
        current.userMessageId,
      ),
      assistantMessageId: optionalString(
        event.data.assistant_message_id,
        current.assistantMessageId,
      ),
      clientMessageId: optionalString(
        event.data.client_message_id,
        current.clientMessageId,
      ),
    }));
  }
  if (event.type === "response.started") {
    // A duplicate response.started must not rewind the cursor (state-machine §4).
    if (event.sequence <= turn.lastSequence) return state;
    return withTurn(state, conversationId, (current) =>
      advance(current, event.sequence, {
        status: "streaming",
        runId: event.run_id,
        userMessageId: optionalString(
          event.data.user_message_id,
          current.userMessageId,
        ),
        assistantMessageId: optionalString(
          event.data.assistant_message_id,
          current.assistantMessageId,
        ),
        clientMessageId: optionalString(
          event.data.client_message_id,
          current.clientMessageId,
        ),
      }),
    );
  }
  if (event.sequence <= turn.lastSequence) return state;
  if (
    KNOWN_EVENT_TYPES.has(event.type) &&
    event.sequence > turn.lastSequence + 1 &&
    turn.lastSequence > 0
  ) {
    return withTurn(state, conversationId, (current) => ({
      ...current,
      status: "reconciling",
    }));
  }
  if (!KNOWN_EVENT_TYPES.has(event.type)) {
    // Contracts §4: ignore unknown types within major 1, but consume the
    // sequence so a later known event is not mistaken for a gap.
    return withTurn(state, conversationId, (current) =>
      advance(current, event.sequence),
    );
  }
  if (event.type === "usage.updated") {
    return withTurn(state, conversationId, (current) =>
      advance(current, event.sequence),
    );
  }
  if (event.type === "message.delta") {
    const delta = optionalString(event.data.delta, "");
    const expectedIndex = contentIndex(turn.assistantContent);
    if (event.data.content_index !== expectedIndex) {
      return withTurn(state, conversationId, (current) =>
        advance(current, event.sequence, { status: "reconciling" }),
      );
    }
    return withTurn(state, conversationId, (current) =>
      advance(current, event.sequence, {
        status: "streaming",
        assistantContent: current.assistantContent + delta,
      }),
    );
  }
  if (event.type === "message.completed") {
    return withTurn(state, conversationId, (current) =>
      advance(current, event.sequence, {
        assistantContent:
          optionalString(event.data.content, current.assistantContent) ??
          current.assistantContent,
        assistantMessageId: optionalString(
          event.data.message_id,
          current.assistantMessageId,
        ),
      }),
    );
  }
  if (event.type === "response.completed") {
    return withTurn(state, conversationId, (current) =>
      advance(current, event.sequence, { status: "completed" }),
    );
  }
  if (event.type === "response.cancelled") {
    return withTurn(state, conversationId, (current) =>
      advance(current, event.sequence, {
        status: "cancelled",
        assistantContent:
          optionalString(event.data.content, current.assistantContent) ??
          current.assistantContent,
      }),
    );
  }
  return withTurn(state, conversationId, (current) =>
    advance(current, event.sequence, {
      status: "failed",
      errorCode: optionalString(event.data.code, "internal_error"),
      diagnosticId: optionalString(event.data.diagnostic_id, null),
      assistantContent:
        optionalString(event.data.content, current.assistantContent) ??
        current.assistantContent,
    }),
  );
}

function snapshotStatus(event: StreamEvent): TurnStatus {
  const status = String(event.data.status ?? "streaming");
  if (status === "queued" || status === "cancelling") return status;
  if (status === "completed" || status === "cancelled" || status === "failed")
    return status;
  return "streaming";
}
