import { describe, expect, test } from "vitest";
import { NextRequest } from "next/server";

import {
  NONCE_HEADER,
  buildCsp,
  middleware,
  STATIC_SECURITY_HEADERS,
} from "../middleware";

describe("browser security headers", () => {
  test("static headers match docs/security.md exactly", () => {
    expect(STATIC_SECURITY_HEADERS).toEqual({
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer",
      "X-Frame-Options": "DENY",
      "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    });
  });

  test("production csp keeps the spec directives with only a script nonce", () => {
    const csp = buildCsp("test-nonce");
    expect(csp).toContain("default-src 'self'");
    expect(csp).toContain("script-src 'self' 'nonce-test-nonce'");
    expect(csp).toContain("style-src 'self' 'unsafe-inline'");
    expect(csp).toContain("img-src 'self' data:");
    expect(csp).toContain("connect-src 'self'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("base-uri 'self'");
    expect(csp).not.toContain("unsafe-eval");
    expect(csp).not.toMatch(/script-src[^;]*unsafe-inline/);
  });

  test("development csp relaxes only eval for the Next HMR runtime", () => {
    const csp = buildCsp("test-nonce", { allowEval: true });
    expect(csp).toContain("script-src 'self' 'nonce-test-nonce' 'unsafe-eval'");
    expect(csp).not.toMatch(/script-src[^;]*unsafe-inline/);
  });

  test("nonces differ per request", () => {
    expect(buildCsp("one")).not.toBe(buildCsp("two"));
  });

  test("middleware forwards a nonce on the request and the CSP header", () => {
    const response = middleware(
      new NextRequest(new URL("http://127.0.0.1:3000/c/demo")),
    );
    const csp = response.headers.get("Content-Security-Policy") ?? "";
    const nonce = /nonce-([^'\s]+)/.exec(csp)?.[1];
    expect(nonce).toBeTruthy();
    expect(csp).toContain(`'nonce-${nonce}'`);
    expect(NONCE_HEADER).toBe("x-nonce");
  });
});
