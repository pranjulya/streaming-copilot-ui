"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import {
  ClientError,
  newClientMessageId,
  newIdempotencyKey,
  type ConversationSnapshot,
  type ConversationClient,
  type Message,
} from "../api/client";
import { chatReducer, emptyTurn, initialChatState } from "../state/chatReducer";
import {
  busyActiveRunId,
  followActiveRun,
  pollRunUntilTerminal,
  streamTurn,
  supportsStreaming,
  type TurnKind,
} from "../state/recovery";
import type { ParseResult } from "../stream/parseNdjson";
import { Composer } from "./Composer";
import { MessageBubble } from "./MessageBubble";
import { StatusText } from "./StatusText";

const ACTIVE_STATUSES = new Set([
  "submitting",
  "connecting",
  "streaming",
  "stopping",
  "reconciling",
]);

const retryableNotice = "Send failed; check your connection and try again.";
const rejectedNotice = "Send failed; your message was not stored.";
const rateLimitedNotice = "Rate limited — try again in a moment.";

async function loadConversationPages(
  client: ConversationClient,
  conversationId: string,
): Promise<ConversationSnapshot> {
  let cursor: string | null = null;
  let combined: ConversationSnapshot | null = null;
  do {
    const page = await client.getConversation(
      conversationId,
      cursor === null ? {} : { cursor },
    );
    combined =
      combined === null
        ? page
        : {
            ...page,
            messages: {
              items: [...combined.messages.items, ...page.messages.items],
              next_cursor: page.messages.next_cursor,
            },
          };
    cursor = page.messages.next_cursor;
  } while (cursor !== null);
  if (combined === null) {
    throw new Error("conversation snapshot was empty");
  }
  return combined;
}

export function Transcript({
  client,
  conversationId,
}: {
  client: ConversationClient;
  conversationId: string;
}) {
  const [snapshot, setSnapshot] = useState<ConversationSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const errorRef = useRef<HTMLDivElement>(null);
  const [state, dispatch] = useReducer(chatReducer, initialChatState);
  const conversationIdRef = useRef(conversationId);
  conversationIdRef.current = conversationId;
  const controllerRef = useRef<AbortController | null>(null);
  const needsRecoveryRef = useRef(false);
  const stateRef = useRef(state);
  stateRef.current = state;

  const loadSnapshot = useCallback(async () => {
    const requestedId = conversationId;
    const result = await loadConversationPages(client, requestedId);
    if (conversationIdRef.current === requestedId) {
      setSnapshot(result);
    }
    return result;
  }, [client, conversationId]);

  useEffect(() => {
    let active = true;
    setSnapshot(null);
    setError(null);
    dispatch({ type: "navigate", conversationId });
    if (!supportsStreaming()) {
      setNotice(
        "Live streaming is unavailable here; answers appear when ready.",
      );
    }
    void loadConversationPages(client, conversationId)
      .then((result) => {
        if (active && conversationIdRef.current === conversationId) {
          setSnapshot(result);
        }
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setError(
          caught instanceof ClientError && caught.status === 404
            ? "This conversation does not exist."
            : "The conversation could not be loaded.",
        );
      });
    return () => {
      active = false;
    };
  }, [client, conversationId]);

  useEffect(() => {
    if (error !== null) errorRef.current?.focus();
  }, [error]);

  const dispatchEvent = useCallback(
    (result: ParseResult) => {
      if (result.kind === "event") {
        dispatch({ type: "event", conversationId, event: result.event });
      } else if (result.kind === "protocol") {
        dispatch({ type: "reconcile", conversationId });
        setNotice(
          "The stream was interrupted; the canonical answer is shown instead.",
        );
      } else {
        setNotice(
          "The stream was interrupted; the canonical answer is shown instead.",
        );
      }
    },
    [conversationId],
  );

  const currentTurn = () =>
    stateRef.current.turnsByConversation[conversationId] ?? emptyTurn();

  const runStreamedTurn = useCallback(
    async (turn: TurnKind, clientMessageId: string, idempotencyKey: string) => {
      const controller = new AbortController();
      controllerRef.current = controller;
      try {
        return await streamTurn({
          client,
          turn,
          clientMessageId,
          idempotencyKey,
          signal: controller.signal,
          onResult: dispatchEvent,
        });
      } finally {
        controllerRef.current = null;
      }
    },
    [client, dispatchEvent],
  );

  const attachToActiveRun = useCallback(
    async (runId: string, afterSequence: number) => {
      const controller = new AbortController();
      controllerRef.current = controller;
      try {
        await followActiveRun({
          runId,
          afterSequence,
          signal: controller.signal,
          onResult: dispatchEvent,
        });
      } catch {
        setNotice("Reconnect failed; showing canonical history instead.");
      } finally {
        controllerRef.current = null;
      }
    },
    [dispatchEvent],
  );

  const submit = useCallback(
    async (content: string) => {
      const clientMessageId = newClientMessageId();
      const idempotencyKey = newIdempotencyKey();
      dispatch({
        type: "optimistic",
        conversationId,
        clientMessageId,
        content,
      });
      const turn: TurnKind = { kind: "create", conversationId, content };
      let result = await runStreamedTurn(turn, clientMessageId, idempotencyKey);
      if (result.outcome === "network-unknown") {
        setNotice("Connection lost; checking whether your message was saved…");
        result = await runStreamedTurn(turn, clientMessageId, idempotencyKey);
      }
      if (result.outcome === "network-unknown") {
        try {
          const latest = await client.getConversation(conversationId);
          if (latest.active_run) {
            await attachToActiveRun(
              latest.active_run.id,
              currentTurn().lastSequence,
            );
          } else if (
            !latest.messages.items.some(
              (message) => message.client_message_id === clientMessageId,
            )
          ) {
            setNotice("Your message was not stored. You can send it again.");
            dispatch({ type: "sendFailed", conversationId });
            throw new Error("Send failed");
          }
        } catch (caught: unknown) {
          if (caught instanceof Error && caught.message === "Send failed") {
            throw caught;
          }
          needsRecoveryRef.current = true;
          setNotice(retryableNotice);
        }
      } else if (result.outcome === "rejected") {
        const active = busyActiveRunId(result.error);
        if (active !== null) {
          setNotice("Another answer is already running; following it.");
          await attachToActiveRun(active, 0);
        } else {
          const code =
            result.error instanceof ClientError
              ? result.error.code
              : "internal_error";
          setNotice(
            code === "rate_limited" ? rateLimitedNotice : rejectedNotice,
          );
          dispatch({ type: "sendFailed", conversationId });
          throw result.error instanceof Error
            ? result.error
            : new Error("Send failed");
        }
      }
      if (conversationIdRef.current === conversationId) {
        try {
          await loadSnapshot();
        } catch {
          // The canonical refetch is best-effort.
        }
      }
    },
    [attachToActiveRun, client, conversationId, loadSnapshot, runStreamedTurn],
  );

  const stop = useCallback(async () => {
    controllerRef.current?.abort();
    dispatch({ type: "stop-requested", conversationId });
    const runId = currentTurn().runId;
    if (runId !== null) {
      try {
        await client.cancelRun(runId);
      } catch {
        // A terminal run is a successful no-op; network errors fall through to polling.
      }
      const settled = await pollRunUntilTerminal(client, runId, {
        delayMs: 300,
        attempts: 20,
      });
      dispatch({
        type: "canonical-status",
        conversationId,
        status: settled?.status ?? "failed",
      });
    }
    try {
      await loadSnapshot();
    } catch {
      // Best-effort.
    }
  }, [client, conversationId, loadSnapshot]);

  const retry = useCallback(async () => {
    const runId = currentTurn().runId;
    if (runId === null) return;
    dispatch({ type: "restart-turn", conversationId });
    const result = await runStreamedTurn(
      { kind: "retry", runId },
      currentTurn().clientMessageId ?? crypto.randomUUID(),
      crypto.randomUUID(),
    );
    if (result.outcome !== "streamed") {
      setNotice(
        result.error instanceof ClientError
          ? `Retry failed (${result.error.code}).`
          : retryableNotice,
      );
    }
    try {
      await loadSnapshot();
    } catch {
      // Best-effort.
    }
  }, [conversationId, loadSnapshot, runStreamedTurn]);

  const regenerate = useCallback(
    async (userMessageId: string) => {
      dispatch({ type: "restart-turn", conversationId });
      const result = await runStreamedTurn(
        { kind: "regenerate", userMessageId },
        crypto.randomUUID(),
        crypto.randomUUID(),
      );
      if (result.outcome !== "streamed") {
        setNotice(
          result.error instanceof ClientError
            ? `Regenerate failed (${result.error.code}).`
            : retryableNotice,
        );
      }
      try {
        await loadSnapshot();
      } catch {
        // Best-effort.
      }
    },
    [conversationId, loadSnapshot, runStreamedTurn],
  );

  const recoverWhenOnline = useCallback(async () => {
    if (!needsRecoveryRef.current) return;
    needsRecoveryRef.current = false;
    try {
      const latest = await client.getConversation(conversationId);
      if (latest.active_run) {
        setNotice("Reconnecting to the running answer…");
        await attachToActiveRun(
          latest.active_run.id,
          currentTurn().lastSequence,
        );
      }
      await loadSnapshot();
    } catch {
      needsRecoveryRef.current = true;
    }
  }, [attachToActiveRun, client, conversationId, loadSnapshot]);

  useEffect(() => {
    const onOnline = () => void recoverWhenOnline();
    window.addEventListener("online", onOnline);
    return () => window.removeEventListener("online", onOnline);
  }, [recoverWhenOnline]);

  if (error !== null) {
    return (
      <section className="transcript" aria-label="Conversation">
        <div
          role="alert"
          className="error-summary"
          ref={errorRef}
          tabIndex={-1}
        >
          {error}
        </div>
      </section>
    );
  }
  if (snapshot === null) {
    return (
      <section className="transcript" aria-label="Conversation">
        <p role="status">Loading conversation…</p>
      </section>
    );
  }

  const turn = state.turnsByConversation[conversationId] ?? emptyTurn();
  const visible = snapshot.messages.items.filter(
    (message) => message.is_visible,
  );
  const canonicalHasUserMessage =
    turn.clientMessageId !== null &&
    visible.some(
      (message) => message.client_message_id === turn.clientMessageId,
    );
  const showLiveUser = turn.userContent !== "" && !canonicalHasUserMessage;
  const canonicalHasAssistant =
    turn.assistantMessageId !== null &&
    visible.some((message) => message.id === turn.assistantMessageId);
  const showLiveAssistant =
    turn.assistantContent !== "" &&
    !canonicalHasAssistant &&
    (ACTIVE_STATUSES.has(turn.status) || turn.status === "completed");
  const lastAssistant = [...visible]
    .reverse()
    .find((message) => message.role === "assistant");
  const regenerateTarget = lastAssistant?.in_reply_to_id ?? null;

  const liveMessage = (role: Message["role"], content: string): Message => ({
    id: `live-${role}`,
    conversation_id: conversationId,
    role,
    content,
    status: "partial",
    client_message_id: turn.clientMessageId,
    in_reply_to_id: null,
    version: 1,
    is_visible: true,
    created_at: new Date().toISOString(),
  });

  const activeRunStatus = snapshot.active_run?.status;
  const statusForIndicator =
    turn.status === "streaming"
      ? "streaming"
      : turn.status === "stopping"
        ? "cancelling"
        : turn.status === "submitting" || turn.status === "connecting"
          ? "queued"
          : activeRunStatus === "queued" ||
              activeRunStatus === "streaming" ||
              activeRunStatus === "cancelling"
            ? activeRunStatus
            : null;

  return (
    <section className="transcript" aria-label="Conversation">
      <h1 className="conversation-title">{snapshot.conversation.title}</h1>
      <StatusText status={statusForIndicator} />
      {visible.length === 0 && !showLiveUser && !showLiveAssistant ? (
        <p className="empty-transcript">No messages yet.</p>
      ) : (
        <ol className="transcript-list" role="list">
          {visible.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))}
          {showLiveUser ? (
            <MessageBubble
              key="live-user"
              message={liveMessage("user", turn.userContent)}
            />
          ) : null}
          {showLiveAssistant ? (
            <MessageBubble
              key="live-assistant"
              message={liveMessage("assistant", turn.assistantContent)}
            />
          ) : null}
        </ol>
      )}
      <div className="turn-controls">
        {ACTIVE_STATUSES.has(turn.status) ? (
          <button type="button" onClick={() => void stop()}>
            Stop
          </button>
        ) : null}
        {turn.runId !== null &&
        (turn.status === "failed" || turn.status === "cancelled") ? (
          <button type="button" onClick={() => void retry()}>
            Retry
          </button>
        ) : null}
        {turn.status === "completed" && regenerateTarget !== null ? (
          <button
            type="button"
            onClick={() => void regenerate(regenerateTarget)}
          >
            Regenerate
          </button>
        ) : null}
      </div>
      <Composer
        busy={ACTIVE_STATUSES.has(turn.status)}
        onSubmit={(content) => submit(content)}
      />
      <p className="composer-notice" role="status">
        {notice}
      </p>
    </section>
  );
}
