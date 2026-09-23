import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, test, vi } from "vitest";
import { AppShell } from "../features/chat/components/AppShell";
import nextConfig from "../next.config";

test("renders the app shell with the Copilot title link", () => {
  const markup = renderToStaticMarkup(createElement(AppShell, null, "content"));
  expect(markup).toContain('class="app-title"');
  expect(markup).toContain("Copilot");
  expect(markup).toContain('aria-live="polite"');
});

test("development routes health and v1 calls to the API", async () => {
  vi.stubEnv("NODE_ENV", "development");
  const routes = await nextConfig.rewrites!();
  vi.unstubAllEnvs();
  expect(routes).toContainEqual({
    source: "/v1/:path*",
    destination: "http://127.0.0.1:8000/v1/:path*",
  });
  expect(routes).toContainEqual({
    source: "/health/:path*",
    destination: "http://127.0.0.1:8000/health/:path*",
  });
});

test("production leaves private readiness behind the deployment edge", async () => {
  const { vi } = await import("vitest");
  vi.stubEnv("NODE_ENV", "production");
  try {
    expect(await nextConfig.rewrites!()).toEqual([]);
  } finally {
    vi.unstubAllEnvs();
  }
});
