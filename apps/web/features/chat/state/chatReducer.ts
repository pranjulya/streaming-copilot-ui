import type { StreamEvent } from "../stream/parseNdjson";

export type TurnStatus =
  | "idle"
  | "submitting"
  | "connecting"
  | "streaming"
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
  | { type: "reset"; conversationId: string };

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

function applyEvent(state: ChatState, conversationId: string, event: StreamEvent): ChatState {
  if (event.type === "heartbeat") return state;
  if (event.type === "response.snapshot") {
    return withTurn(state, conversationId, (turn) => ({
      ...turn,
      status: snapshotStatus(event),
      assistantContent: String(event.data.content ?? turn.assistantContent),
      lastSequence: Number(event.data.last_sequence ?? turn.lastSequence),
    }));
  }
  if (event.type === "response.started") {
    return withTurn(state, conversationId, (turn) => ({
      ...turn,
      status: "streaming",
      userMessageId: String(event.data.user_message_id ?? turn.userMessageId),
      assistantMessageId: String(event.data.assistant_message_id ?? turn.assistantMessageId),
      clientMessageId: String(event.data.client_message_id ?? turn.clientMessageId),
      runId: event.run_id,
      lastSequence: event.sequence,
    }));
  }
  if (
    event.type === "message.delta" ||
    event.type === "usage.updated" ||
    event.type === "message.completed" ||
    event.type === "response.completed" ||
    event.type === "response.cancelled" ||
    event.type === "response.failed"
  ) {
    if (event.sequence <= state.turnsByConversation[conversationId]?.lastSequence) {
      return state;
    }
    const turn = state.turnsByConversation[conversationId] ?? emptyTurn();
    if (event.sequence > turn.lastSequence + 1 && turn.lastSequence > 0) {
      return withTurn(state, conversationId, (current) => ({
        ...current,
        status: "reconciling",
      }));
    }
    if (event.type === "usage.updated") {
      return withTurn(state, conversationId, (current) => ({
        ...current,
        lastSequence: event.sequence,
      }));
    }
    if (event.type === "message.delta") {
      const delta = String(event.data.delta ?? "");
      const expectedIndex = contentIndex(turn.assistantContent);
      if (event.data.content_index !== expectedIndex) {
        return withTurn(state, conversationId, (current) => ({
          ...current,
          status: "reconciling",
        }));
      }
      return withTurn(state, conversationId, (current) => ({
        ...current,
        status: "streaming",
        assistantContent: current.assistantContent + delta,
        lastSequence: event.sequence,
      }));
    }
    if (event.type === "message.completed") {
      return withTurn(state, conversationId, (current) => ({
        ...current,
        assistantContent: String(event.data.content ?? current.assistantContent),
        assistantMessageId: String(event.data.message_id ?? current.assistantMessageId),
        lastSequence: event.sequence,
      }));
    }
    if (event.type === "response.completed") {
      return withTurn(state, conversationId, (current) => ({
        ...current,
        status: "completed",
        lastSequence: event.sequence,
      }));
    }
    if (event.type === "response.cancelled") {
      return withTurn(state, conversationId, (current) => ({
        ...current,
        status: "cancelled",
        assistantContent:
          event.data.content === undefined
            ? current.assistantContent
            : String(event.data.content),
        lastSequence: event.sequence,
      }));
    }
    return withTurn(state, conversationId, (current) => ({
      ...current,
      status: "failed",
      errorCode: String(event.data.code ?? "internal_error"),
      diagnosticId:
        event.data.diagnostic_id === undefined ? null : String(event.data.diagnostic_id),
      assistantContent:
        event.data.content === undefined ? current.assistantContent : String(event.data.content),
      lastSequence: event.sequence,
    }));
  }
  return state;
}

function snapshotStatus(event: StreamEvent): TurnStatus {
  const status = String(event.data.status ?? "streaming");
  if (status === "queued" || status === "cancelling") return status;
  if (status === "completed" || status === "cancelled" || status === "failed") return status;
  return "streaming";
}
