"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import type { Conversation, ConversationClient } from "../api/client";
import { ClientError } from "../api/client";

type ListState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; items: Conversation[]; nextCursor: string | null };

function problemMessage(caught: unknown, fallback: string): string {
  return caught instanceof ClientError ? caught.message : fallback;
}

function mergeById(
  primary: Conversation[],
  extra: Conversation[],
): Conversation[] {
  const seen = new Set(primary.map((item) => item.id));
  const merged = [...primary];
  for (const item of extra) {
    if (!seen.has(item.id)) {
      seen.add(item.id);
      merged.push(item);
    }
  }
  return merged;
}

export function ConversationList({ client }: { client: ConversationClient }) {
  const [state, setState] = useState<ListState>({ kind: "loading" });
  const [showArchived, setShowArchived] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [notice, setNotice] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const loadGeneration = useRef(0);
  const pendingCreated = useRef<Conversation[]>([]);

  const load = useCallback(
    async (options: {
      archived: boolean;
      cursor?: string | null;
      append?: boolean;
    }) => {
      const generation = ++loadGeneration.current;
      if (!options.append) {
        setState((current) =>
          current.kind === "ready" ? current : { kind: "loading" },
        );
      }
      try {
        const page = await client.listConversations({
          includeArchived: options.archived,
          cursor: options.cursor ?? null,
        });
        if (generation !== loadGeneration.current) return;
        setState((current) => {
          const pending = pendingCreated.current;
          pendingCreated.current = [];
          const existing =
            options.append && current.kind === "ready" ? current.items : [];
          const incoming = options.append
            ? page.items
            : mergeById(pending, page.items);
          return {
            kind: "ready",
            items: mergeById(existing, incoming),
            nextCursor: page.next_cursor,
          };
        });
      } catch (caught: unknown) {
        if (generation !== loadGeneration.current) return;
        setState({
          kind: "error",
          message: problemMessage(caught, "Conversations could not be loaded."),
        });
      }
    },
    [client],
  );

  useEffect(() => {
    void load({ archived: showArchived });
  }, [load, showArchived]);

  function replaceItem(updated: Conversation) {
    setState((current) =>
      current.kind === "ready"
        ? {
            ...current,
            items: current.items.map((item) =>
              item.id === updated.id ? updated : item,
            ),
          }
        : current,
    );
  }

  async function archive(conversation: Conversation) {
    if (!window.confirm(`Archive “${conversation.title}”?`)) return;
    try {
      setActionError(null);
      const updated = await client.patchConversation(conversation.id, {
        archived: true,
      });
      setNotice(`Archived “${conversation.title}”.`);
      replaceItem(updated);
    } catch (caught: unknown) {
      setActionError(
        problemMessage(caught, "The conversation could not be archived."),
      );
    }
  }

  async function undoArchive(conversation: Conversation) {
    try {
      setActionError(null);
      const updated = await client.patchConversation(conversation.id, {
        archived: false,
      });
      setNotice(`Restored “${conversation.title}”.`);
      replaceItem(updated);
    } catch (caught: unknown) {
      setActionError(
        problemMessage(caught, "The conversation could not be restored."),
      );
    }
  }

  async function saveRename(conversation: Conversation) {
    const title = renameDraft.trim();
    if (!title) return;
    try {
      setActionError(null);
      const updated = await client.patchConversation(conversation.id, {
        title,
      });
      setRenamingId(null);
      setRenameDraft("");
      replaceItem(updated);
    } catch (caught: unknown) {
      setActionError(
        problemMessage(caught, "The conversation could not be renamed."),
      );
    }
  }

  async function createConversation() {
    try {
      setActionError(null);
      const conversation = await client.createConversation();
      setState((current) => {
        if (current.kind === "ready") {
          return {
            ...current,
            items: mergeById([conversation], current.items),
          };
        }
        pendingCreated.current = mergeById(
          [conversation],
          pendingCreated.current,
        );
        return current;
      });
    } catch (caught: unknown) {
      setActionError(
        problemMessage(caught, "The conversation could not be created."),
      );
    }
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
      {actionError !== null ? (
        <div role="alert" className="error-summary">
          {actionError}
        </div>
      ) : null}

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
        <ul className="conversation-items" role="list">
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
      {state.kind === "ready" && state.nextCursor !== null ? (
        <button
          type="button"
          onClick={() =>
            void load({
              archived: showArchived,
              cursor: state.nextCursor,
              append: true,
            })
          }
        >
          Load more
        </button>
      ) : null}
    </section>
  );
}
