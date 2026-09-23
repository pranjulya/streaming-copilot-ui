"use client";

import type { Message } from "../api/client";
import { SafeMarkdown } from "../markdown/SafeMarkdown";

const STATUS_LABELS: Record<Message["status"], string> = {
  complete: "",
  partial: "Still generating",
  cancelled: "Stopped",
  failed: "Failed",
};

export function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  const statusLabel = STATUS_LABELS[message.status];
  return (
    <li
      className={`message-bubble message-bubble--${message.role}`}
      data-role={message.role}
    >
      <p className="message-role">{isUser ? "You" : "Copilot"}</p>
      <div className="message-content">
        {isUser ? (
          <p className="message-text">{message.content}</p>
        ) : (
          <div className="message-text">
            <SafeMarkdown content={message.content} />
          </div>
        )}
      </div>
      {statusLabel ? <p className="message-status">{statusLabel}</p> : null}
    </li>
  );
}
