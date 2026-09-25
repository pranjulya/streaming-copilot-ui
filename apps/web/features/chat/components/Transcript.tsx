"use client";

import { useEffect, useRef, useState } from "react";

import type { ConversationSnapshot, ConversationClient } from "../api/client";
import { ClientError } from "../api/client";
import { Composer } from "./Composer";
import { MessageBubble } from "./MessageBubble";
import { StatusText } from "./StatusText";

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

  useEffect(() => {
    let active = true;
    setSnapshot(null);
    setError(null);
    void (async () => {
      try {
        let cursor: string | null = null;
        let combined: ConversationSnapshot | null = null;
        do {
          const page = await client.getConversation(
            conversationId,
            cursor === null ? {} : { cursor },
          );
          if (!active) return;
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
        if (active) setSnapshot(combined);
      } catch (caught: unknown) {
        if (!active) return;
        setError(
          caught instanceof ClientError && caught.status === 404
            ? "This conversation does not exist."
            : "The conversation could not be loaded.",
        );
      }
    })();
    return () => {
      active = false;
    };
  }, [client, conversationId]);

  useEffect(() => {
    if (error !== null) errorRef.current?.focus();
  }, [error]);

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

  const visible = snapshot.messages.items.filter(
    (message) => message.is_visible,
  );
  const activeStatus = snapshot.active_run?.status;
  return (
    <section className="transcript" aria-label="Conversation">
      <h1 className="conversation-title">{snapshot.conversation.title}</h1>
      <StatusText
        status={
          activeStatus === "queued" ||
          activeStatus === "streaming" ||
          activeStatus === "cancelling"
            ? activeStatus
            : null
        }
      />
      {visible.length === 0 ? (
        <p className="empty-transcript">No messages yet.</p>
      ) : (
        <ol className="transcript-list" role="list">
          {visible.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))}
        </ol>
      )}
      <Composer
        onSubmit={() => {
          setNotice("Sending is not available yet.");
        }}
      />
      <p className="composer-notice" role="status">
        {notice}
      </p>
    </section>
  );
}
