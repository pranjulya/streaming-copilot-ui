// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, describe, expect, test, vi } from "vitest";

import type { ConversationClient, ConversationSnapshot } from "../../features/chat/api/client";
import { Composer } from "../../features/chat/components/Composer";
import { Transcript } from "../../features/chat/components/Transcript";

afterEach(cleanup);

const MESSAGE = {
  id: "0195f4db-0000-7000-8000-000000000001",
  conversation_id: "0195f4da-0000-7000-8000-000000000001",
  role: "user" as const,
  content: "Hello there",
  status: "complete" as const,
  client_message_id: "0195f4d8-4ee0-7a35-8bc4-63cb5966b448",
  in_reply_to_id: null,
  version: 1,
  is_visible: true,
  created_at: "2026-09-09T10:29:00.000Z",
};

function snapshot(): ConversationSnapshot {
  return {
    conversation: {
      id: "0195f4da-0000-7000-8000-000000000001",
      title: "Explain backpressure",
      created_at: "2026-09-09T10:29:00.000Z",
      updated_at: "2026-09-09T10:30:00.000Z",
      archived_at: null,
      active_run_id: null,
    },
    messages: { items: [MESSAGE], next_cursor: null },
    active_run: null,
  };
}

describe("Composer", () => {
  test("Enter submits and clears, Shift+Enter inserts a newline", async () => {
    const onSubmit = vi.fn();
    render(<Composer onSubmit={onSubmit} />);
    const input = screen.getByLabelText("Message");

    await userEvent.type(input, "line one{Shift>}{Enter}{/Shift}line two");
    expect(onSubmit).not.toHaveBeenCalled();
    expect((input as HTMLTextAreaElement).value).toBe("line one\nline two");

    await userEvent.type(input, "{Enter}");
    expect(onSubmit).toHaveBeenCalledWith("line one\nline two");
    expect((input as HTMLTextAreaElement).value).toBe("");
  });

  test("submit button is disabled while the composer is empty", async () => {
    render(<Composer onSubmit={() => {}} />);
    const button = screen.getByRole("button", { name: "Send" });
    expect(button.hasAttribute("disabled")).toBe(true);
    await userEvent.type(screen.getByLabelText("Message"), "hi");
    expect(button.hasAttribute("disabled")).toBe(false);
  });

  test("does not call any write API in this phase", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(<Composer onSubmit={() => {}} />);
    await userEvent.type(screen.getByLabelText("Message"), "hello{Enter}");
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });
});

describe("accessibility", () => {
  test("transcript has no axe violations", async () => {
    const client = {
      getConversation: vi.fn().mockResolvedValue(snapshot()),
    } as unknown as ConversationClient;
    const { container } = render(
      <Transcript client={client} conversationId="0195f4da-0000-7000-8000-000000000001" />,
    );
    await screen.findByRole("heading", { name: "Explain backpressure" });
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations).toEqual([]);
  });

  test("composer has no axe violations", async () => {
    const { container } = render(<Composer onSubmit={() => {}} />);
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations).toEqual([]);
  });
});

describe("reduced motion", () => {
  test("token animation is disabled under prefers-reduced-motion", async () => {
    const { readFile } = await import("node:fs/promises");
    const { resolve } = await import("node:path");
    const css = await readFile(resolve(process.cwd(), "app/globals.css"), "utf8");
    expect(css).toContain("@media (prefers-reduced-motion: reduce)");
    expect(css).toMatch(/\.token-animation\s*\{\s*animation:\s*none;/);
  });
});
