// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import type {
  Conversation,
  ConversationClient,
} from "../../features/chat/api/client";
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
      await screen.findByRole("button", { name: "Archive" }),
    );
    expect(confirmSpy).toHaveBeenCalled();
    expect(patch).not.toHaveBeenCalled();

    confirmSpy.mockReturnValue(true);
    await userEvent.click(screen.getByRole("button", { name: "Archive" }));
    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith(conversation().id, { archived: true }),
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
      await screen.findByRole("button", { name: "Restore" }),
    );
    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith(conversation().id, {
        archived: false,
      }),
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
      await screen.findByRole("button", { name: "Rename" }),
    );
    const input = screen.getByLabelText("Rename conversation");
    await userEvent.clear(input);
    await userEvent.type(input, "  Renamed  ");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith(conversation().id, {
        title: "Renamed",
      }),
    );
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
});
