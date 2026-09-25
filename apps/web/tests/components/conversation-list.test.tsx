// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import type {
  Conversation,
  ConversationClient,
} from "../../features/chat/api/client";
import { ClientError } from "../../features/chat/api/client";
import { ConversationList } from "../../features/chat/components/ConversationList";

afterEach(cleanup);

function conversation(overrides: Partial<Conversation> = {}): Conversation {
  return {
    id: "0195f4da-0000-7000-8000-000000000001",
    title: "First conversation",
    created_at: "2026-09-09T10:29:00.000Z",
    updated_at: "2026-09-09T10:30:00.000Z",
    archived_at: null,
    active_run_id: null,
    ...overrides,
  };
}

function stubClient(
  overrides: Partial<ConversationClient> = {},
): ConversationClient {
  return {
    listConversations: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    getConversation: vi.fn(),
    createConversation: vi.fn(),
    patchConversation: vi.fn().mockResolvedValue(conversation()),
    ...overrides,
  } as unknown as ConversationClient;
}

describe("ConversationList", () => {
  test("renders conversations as links", async () => {
    const client = stubClient({
      listConversations: vi
        .fn()
        .mockResolvedValue({ items: [conversation()], next_cursor: null }),
    });
    render(<ConversationList client={client} />);
    const link = await screen.findByRole("link", {
      name: "First conversation",
    });
    expect(link.getAttribute("href")).toBe(
      "/c/0195f4da-0000-7000-8000-000000000001",
    );
  });

  test("shows an empty state without conversations", async () => {
    render(<ConversationList client={stubClient()} />);
    expect(await screen.findByText("No conversations yet.")).toBeTruthy();
  });

  test("shows an alert when loading fails", async () => {
    const client = stubClient({
      listConversations: vi.fn().mockRejectedValue(new Error("network down")),
    });
    render(<ConversationList client={client} />);
    expect(await screen.findByRole("alert")).toBeTruthy();
  });

  test("archive asks for confirmation before patching", async () => {
    const patch = vi
      .fn()
      .mockResolvedValue(
        conversation({ archived_at: "2026-09-09T11:00:00.000Z" }),
      );
    const client = stubClient({
      listConversations: vi
        .fn()
        .mockResolvedValue({ items: [conversation()], next_cursor: null }),
      patchConversation: patch,
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<ConversationList client={client} />);
    await userEvent.click(
      await screen.findByRole("button", { name: /^Archive/ }),
    );
    expect(confirmSpy).toHaveBeenCalled();
    expect(patch).not.toHaveBeenCalled();

    confirmSpy.mockReturnValue(true);
    await userEvent.click(screen.getByRole("button", { name: /^Archive/ }));
    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith(
        conversation().id,
        { archived: true },
        expect.objectContaining({ idempotencyKey: expect.any(String) }),
      ),
    );
    expect(await screen.findByText(/Archived/)).toBeTruthy();
    confirmSpy.mockRestore();
  });

  test("restore unarchives with archived false", async () => {
    const patch = vi.fn().mockResolvedValue(conversation());
    const client = stubClient({
      listConversations: vi.fn().mockResolvedValue({
        items: [conversation({ archived_at: "2026-09-09T11:00:00.000Z" })],
        next_cursor: null,
      }),
      patchConversation: patch,
    });
    render(<ConversationList client={client} />);
    await userEvent.click(
      await screen.findByRole("button", { name: /^Restore/ }),
    );
    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith(
        conversation().id,
        { archived: false },
        expect.objectContaining({ idempotencyKey: expect.any(String) }),
      ),
    );
  });

  test("rename saves the trimmed title inline", async () => {
    const patch = vi.fn().mockResolvedValue(conversation({ title: "Renamed" }));
    const client = stubClient({
      listConversations: vi
        .fn()
        .mockResolvedValue({ items: [conversation()], next_cursor: null }),
      patchConversation: patch,
    });
    render(<ConversationList client={client} />);
    await userEvent.click(
      await screen.findByRole("button", { name: /^Rename/ }),
    );
    const input = screen.getByLabelText("Rename conversation");
    await userEvent.clear(input);
    await userEvent.type(input, "  Renamed  ");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith(
        conversation().id,
        { title: "Renamed" },
        expect.objectContaining({ idempotencyKey: expect.any(String) }),
      ),
    );
  });

  test("archive failure shows an error summary", async () => {
    const client = stubClient({
      listConversations: vi
        .fn()
        .mockResolvedValue({ items: [conversation()], next_cursor: null }),
      patchConversation: vi
        .fn()
        .mockRejectedValue(
          new ClientError(
            409,
            "conversation_busy",
            "Conversation is busy",
            null,
          ),
        ),
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<ConversationList client={client} />);
    await userEvent.click(
      await screen.findByRole("button", { name: /^Archive/ }),
    );
    expect((await screen.findByRole("alert")).textContent).toContain(
      "Conversation is busy",
    );
    vi.mocked(window.confirm).mockRestore();
  });

  test("ignores a stale list response after a newer load", async () => {
    let resolveFirst: (value: {
      items: Conversation[];
      next_cursor: string | null;
    }) => void = () => {};
    const first = new Promise<{
      items: Conversation[];
      next_cursor: string | null;
    }>((resolve) => {
      resolveFirst = resolve;
    });
    const listConversations = vi
      .fn()
      .mockReturnValueOnce(first)
      .mockResolvedValueOnce({
        items: [conversation({ title: "Archived view" })],
        next_cursor: null,
      });
    render(<ConversationList client={stubClient({ listConversations })} />);
    await userEvent.click(screen.getByLabelText("Show archived"));
    expect(await screen.findByText("Archived view")).toBeTruthy();
    resolveFirst({
      items: [conversation({ title: "Stale view" })],
      next_cursor: null,
    });
    await waitFor(() => expect(screen.queryByText("Stale view")).toBeNull());
    expect(screen.getByText("Archived view")).toBeTruthy();
  });

  test("keeps a create that races the initial list load", async () => {
    let resolveList: (value: {
      items: Conversation[];
      next_cursor: string | null;
    }) => void = () => {};
    const list = new Promise<{
      items: Conversation[];
      next_cursor: string | null;
    }>((resolve) => {
      resolveList = resolve;
    });
    const created = conversation({
      id: "0195f4da-0000-7000-8000-0000000000aa",
      title: "Created while loading",
    });
    const client = stubClient({
      listConversations: vi.fn().mockReturnValue(list),
      createConversation: vi.fn().mockResolvedValue(created),
    });
    render(<ConversationList client={client} />);
    expect(screen.getByText("Loading conversations…")).toBeTruthy();
    await userEvent.click(
      screen.getByRole("button", { name: "New conversation" }),
    );
    resolveList({ items: [], next_cursor: null });
    expect(
      await screen.findByRole("link", { name: "Created while loading" }),
    ).toBeTruthy();
  });

  test("load more appends the next page of conversations", async () => {
    const first = conversation({ title: "Newest" });
    const second = conversation({
      id: "0195f4da-0000-7000-8000-000000000002",
      title: "Older",
    });
    const listConversations = vi
      .fn()
      .mockResolvedValueOnce({ items: [first], next_cursor: "page-2" })
      .mockResolvedValueOnce({ items: [second], next_cursor: null });
    render(<ConversationList client={stubClient({ listConversations })} />);
    expect(await screen.findByText("Newest")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText("Older")).toBeTruthy();
    expect(screen.getByText("Newest")).toBeTruthy();
    expect(listConversations.mock.calls[1][0]).toMatchObject({
      cursor: "page-2",
    });
  });

  test("archived conversations stay visible with Restore", async () => {
    const patch = vi
      .fn()
      .mockResolvedValue(
        conversation({ archived_at: "2026-09-09T11:00:00.000Z" }),
      );
    const client = stubClient({
      listConversations: vi
        .fn()
        .mockResolvedValue({ items: [conversation()], next_cursor: null }),
      patchConversation: patch,
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<ConversationList client={client} />);
    await userEvent.click(
      await screen.findByRole("button", { name: /^Archive/ }),
    );
    expect(
      await screen.findByRole("button", { name: /^Restore/ }),
    ).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "First conversation" }),
    ).toBeTruthy();
    vi.mocked(window.confirm).mockRestore();
  });

  test("new conversation button creates and prepends", async () => {
    const created = conversation({
      id: "0195f4da-0000-7000-8000-0000000000ff",
      title: "New conversation",
    });
    const client = stubClient({
      listConversations: vi
        .fn()
        .mockResolvedValue({ items: [conversation()], next_cursor: null }),
      createConversation: vi.fn().mockResolvedValue(created),
    });
    render(<ConversationList client={client} />);
    await userEvent.click(
      await screen.findByRole("button", { name: "New conversation" }),
    );
    expect(
      await screen.findByRole("link", { name: "New conversation" }),
    ).toBeTruthy();
  });

  test("names row actions after the conversation title", async () => {
    const client = stubClient({
      listConversations: vi
        .fn()
        .mockResolvedValue({ items: [conversation()], next_cursor: null }),
    });
    render(<ConversationList client={client} />);
    expect(
      await screen.findByRole("button", {
        name: "Archive “First conversation”",
      }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Rename “First conversation”" }),
    ).toBeTruthy();
  });

  test("reuses the idempotency key when an archive retry follows a failure", async () => {
    const patch = vi
      .fn()
      .mockRejectedValueOnce(
        new ClientError(500, "internal_error", "boom", null),
      )
      .mockResolvedValueOnce(
        conversation({ archived_at: "2026-09-09T11:00:00.000Z" }),
      );
    const client = stubClient({
      listConversations: vi
        .fn()
        .mockResolvedValue({ items: [conversation()], next_cursor: null }),
      patchConversation: patch,
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<ConversationList client={client} />);
    await userEvent.click(
      await screen.findByRole("button", { name: /^Archive/ }),
    );
    await screen.findByRole("alert");
    await userEvent.click(screen.getByRole("button", { name: /^Archive/ }));
    await screen.findByRole("button", { name: /^Restore/ });
    expect(patch).toHaveBeenCalledTimes(2);
    const first = patch.mock.calls[0][2] as { idempotencyKey: string };
    const second = patch.mock.calls[1][2] as { idempotencyKey: string };
    expect(second.idempotencyKey).toBe(first.idempotencyKey);
    vi.mocked(window.confirm).mockRestore();
  });

  test("moves focus to the error summary when a mutation fails", async () => {
    const client = stubClient({
      listConversations: vi
        .fn()
        .mockResolvedValue({ items: [conversation()], next_cursor: null }),
      patchConversation: vi
        .fn()
        .mockRejectedValue(
          new ClientError(
            409,
            "conversation_busy",
            "Conversation is busy",
            null,
          ),
        ),
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<ConversationList client={client} />);
    await userEvent.click(
      await screen.findByRole("button", { name: /^Archive/ }),
    );
    const alert = await screen.findByRole("alert");
    await waitFor(() => expect(document.activeElement).toBe(alert));
    vi.mocked(window.confirm).mockRestore();
  });

  test("returns focus to the row action after archiving", async () => {
    const patch = vi
      .fn()
      .mockResolvedValue(
        conversation({ archived_at: "2026-09-09T11:00:00.000Z" }),
      );
    const client = stubClient({
      listConversations: vi
        .fn()
        .mockResolvedValue({ items: [conversation()], next_cursor: null }),
      patchConversation: patch,
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<ConversationList client={client} />);
    await userEvent.click(
      await screen.findByRole("button", { name: /^Archive/ }),
    );
    const restore = await screen.findByRole("button", { name: /^Restore/ });
    await waitFor(() => expect(document.activeElement).toBe(restore));
    vi.mocked(window.confirm).mockRestore();
  });
});
