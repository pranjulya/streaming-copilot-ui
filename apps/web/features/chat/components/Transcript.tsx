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
import { startResponse } from "../api/stream";
import { chatReducer, emptyTurn, initialChatState } from "../state/chatReducer";
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
      const controller = new AbortController();
      try {
        await startResponse({
          conversationId,
          content,
          clientMessageId,
          idempotencyKey,
          signal: controller.signal,
          onResult: (result) => {
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
        });
      } catch (caught: unknown) {
        dispatch({ type: "sendFailed", conversationId });
        setNotice(
          caught instanceof ClientError
            ? `Send failed (${caught.code}).`
            : "Send failed; check your connection.",
        );
        throw caught instanceof Error ? caught : new Error("Send failed");
      } finally {
        if (conversationIdRef.current === conversationId) {
          try {
            await loadSnapshot();
          } catch {
            // The canonical refetch is best-effort after streaming ends.
          }
        }
      }
    },
    [conversationId, loadSnapshot],
  );

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
