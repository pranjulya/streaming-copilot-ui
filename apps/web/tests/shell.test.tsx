import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, test, vi } from "vitest";
import Page from "../app/page";
import nextConfig from "../next.config";

test("renders the Phase 00 heading", () => {
  expect(renderToStaticMarkup(createElement(Page))).toBe("<h1>Copilot</h1>");
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
