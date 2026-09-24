// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test } from "vitest";

import type { Message } from "../../features/chat/api/client";
import { MessageBubble } from "../../features/chat/components/MessageBubble";
import { SafeMarkdown } from "../../features/chat/markdown/SafeMarkdown";

afterEach(cleanup);

const XSS_CORPUS = [
  '<script>window.__xss = "script";</script>',
  "<img src=x onerror=\"window.__xss = 'img'\">",
  "[click me](javascript:window.__xss='link')",
  "![xss](javascript:window.__xss='mdimg')",
  '<iframe src="https://evil.example"></iframe>',
  "<a href=\"javascript:alert('href')\">js anchor</a>",
  "<style>body { background: red }</style>",
];

describe("SafeMarkdown", () => {
  test("renders headings, emphasis and lists", () => {
    render(
      <SafeMarkdown
        content={"# Title\n\nSome **bold** and a list:\n\n- one\n- two"}
      />,
    );
    expect(screen.getByRole("heading", { name: "Title" })).toBeTruthy();
    expect(screen.getByText("bold").tagName.toLowerCase()).toBe("strong");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  test("never executes hostile HTML from the XSS corpus", () => {
    const { container } = render(
      <SafeMarkdown content={XSS_CORPUS.join("\n\n")} />,
    );
    expect((globalThis as Record<string, unknown>).__xss).toBeUndefined();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("iframe")).toBeNull();
    expect(container.querySelector("style")).toBeNull();
    for (const image of Array.from(container.querySelectorAll("img"))) {
      expect(image.getAttribute("src") ?? "").not.toMatch(/^\s*javascript:/i);
    }
    for (const anchor of Array.from(container.querySelectorAll("a"))) {
      expect(anchor.getAttribute("href") ?? "").not.toMatch(/^\s*javascript:/i);
    }
  });

  test("never parses raw html into elements", () => {
    const { container } = render(<SafeMarkdown content={"<b>not bold</b>"} />);
    expect(container.querySelector("b")).toBeNull();
    expect(container.textContent).toContain("not bold");
  });

  test("assistant bubbles render markdown and sanitize hostile content", () => {
    const base: Message = {
      id: "0195f4db-0000-7000-8000-000000000002",
      conversation_id: "0195f4da-0000-7000-8000-000000000001",
      role: "assistant",
      content: "## Answer\n\n<script>window.__bubble = 1</script>",
      status: "complete",
      client_message_id: null,
      in_reply_to_id: "0195f4db-0000-7000-8000-000000000001",
      version: 1,
      is_visible: true,
      created_at: "2026-09-09T10:29:10.000Z",
    };
    const { container } = render(<MessageBubble message={base} />);
    expect(screen.getByRole("heading", { name: "Answer" })).toBeTruthy();
    expect(container.querySelector("script")).toBeNull();
    expect((globalThis as Record<string, unknown>).__bubble).toBeUndefined();
  });
});
