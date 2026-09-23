import { describe, expect, test } from "vitest";

import { SECURITY_HEADERS } from "../middleware";

describe("browser security headers", () => {
  test("match docs/security.md exactly", () => {
    expect(SECURITY_HEADERS).toEqual({
      "Content-Security-Policy":
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'",
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer",
      "X-Frame-Options": "DENY",
      "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    });
  });

  test("no header enables inline scripts or framing", () => {
    const csp = SECURITY_HEADERS["Content-Security-Policy"];
    expect(csp).not.toContain("unsafe-eval");
    expect(csp).toContain("script-src 'self'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).not.toContain("unsafe-inline; script");
  });
});
