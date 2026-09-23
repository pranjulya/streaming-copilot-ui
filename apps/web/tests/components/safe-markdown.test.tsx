// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test } from "vitest";

import { SafeMarkdown } from "../../features/chat/markdown/SafeMarkdown";

afterEach(cleanup);

const XSS_CORPUS = [
  '<script>window.__xss = "script";</script>',
  "<img src=x onerror=\"window.__xss = 'img'\">",
  "[click me](javascript:window.__xss='link')",
  "<iframe src=\"https://evil.example\"></iframe>",
  "<a href=\"javascript:alert('href')\">js anchor</a>",
  "<style>body { background: red }</style>",
];

describe("SafeMarkdown", () => {
  test("renders headings, emphasis and lists", () => {
    render(<SafeMarkdown content={"# Title\n\nSome **bold** and a list:\n\n- one\n- two"} />);
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
    expect(container.querySelector("img")).toBeNull();
    for (const anchor of Array.from(container.querySelectorAll("a"))) {
      expect(anchor.getAttribute("href") ?? "").not.toMatch(/^\s*javascript:/i);
    }
  });

  test("keeps raw html text escaped rather than parsed", () => {
    const { container } = render(<SafeMarkdown content={"<b>not bold</b>"} />);
    expect(container.querySelector("b")).toBeNull();
    expect(container.textContent).toContain("<b>not bold</b>");
  });
});
