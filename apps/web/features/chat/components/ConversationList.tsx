"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import type { Conversation, ConversationClient } from "../api/client";
import { ClientError } from "../api/client";

type ListState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; items: Conversation[]; nextCursor: string | null };

export function ConversationList({ client }: { client: ConversationClient }) {
  const [state, setState] = useState<ListState>({ kind: "loading" });
  const [showArchived, setShowArchived] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(
    async (options: { archived: boolean; cursor?: string | null }) => {
      setState({ kind: "loading" });
      try {
        const page = await client.listConversations({
          includeArchived: options.archived,
          cursor: options.cursor ?? null,
        });
        setState({
          kind: "ready",
          items: page.items,
          nextCursor: page.next_cursor,
        });
      } catch (caught: unknown) {
        const message =
          caught instanceof ClientError && caught.status === 401
            ? "You are not signed in."
            : "Conversations could not be loaded.";
        setState({ kind: "error", message });
      }
    },
    [client],
  );

  useEffect(() => {
    void load({ archived: showArchived });
  }, [load, showArchived]);

  async function archive(conversation: Conversation) {
    if (!window.confirm(`Archive “${conversation.title}”?`)) return;
    await client.patchConversation(conversation.id, { archived: true });
    setNotice(`Archived “${conversation.title}”.`);
    await load({ archived: showArchived });
  }

  async function undoArchive(conversation: Conversation) {
    await client.patchConversation(conversation.id, { archived: false });
    setNotice(`Restored “${conversation.title}”.`);
    await load({ archived: showArchived });
  }

  async function saveRename(conversation: Conversation) {
    const title = renameDraft.trim();
    if (!title) return;
    await client.patchConversation(conversation.id, { title });
    setRenamingId(null);
    setRenameDraft("");
    await load({ archived: showArchived });
  }

  async function createConversation() {
    const conversation = await client.createConversation();
    setState((current) =>
      current.kind === "ready"
        ? { ...current, items: [conversation, ...current.items] }
        : current,
    );
  }

  return (
    <section className="conversation-list" aria-label="Conversations">
      <div className="list-toolbar">
        <button type="button" onClick={() => void createConversation()}>
          New conversation
        </button>
        <label className="archived-toggle">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(event) => setShowArchived(event.target.checked)}
          />
          Show archived
        </label>
      </div>
      <p role="status" className="list-notice">
        {notice}
      </p>

      {state.kind === "loading" ? (
        <p role="status">Loading conversations…</p>
      ) : null}
      {state.kind === "error" ? (
        <div role="alert" className="error-summary">
          {state.message}
        </div>
      ) : null}

      {state.kind === "ready" && state.items.length === 0 ? (
        <p className="empty-list">No conversations yet.</p>
      ) : null}
      {state.kind === "ready" && state.items.length > 0 ? (
        <ul className="conversation-items">
          {state.items.map((conversation) => (
            <li key={conversation.id} className="conversation-item">
              {renamingId === conversation.id ? (
                <form
                  className="rename-form"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void saveRename(conversation);
                  }}
                >
                  <label>
                    Rename conversation
                    <input
                      value={renameDraft}
                      onChange={(event) => setRenameDraft(event.target.value)}
                      autoFocus
                    />
                  </label>
                  <button type="submit">Save</button>
                  <button type="button" onClick={() => setRenamingId(null)}>
                    Cancel
                  </button>
                </form>
              ) : (
                <>
                  <Link
                    href={`/c/${conversation.id}`}
                    className="conversation-link"
                  >
                    {conversation.title}
                  </Link>
                  <div className="item-actions">
                    <button
                      type="button"
                      onClick={() => {
                        setRenamingId(conversation.id);
                        setRenameDraft(conversation.title);
                      }}
                    >
                      Rename
                    </button>
                    {conversation.archived_at === null ? (
                      <button
                        type="button"
                        onClick={() => void archive(conversation)}
                      >
                        Archive
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={() => void undoArchive(conversation)}
                      >
                        Restore
                      </button>
                    )}
                  </div>
                </>
              )}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
