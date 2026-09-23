import { NextResponse, type NextRequest } from "next/server";

export function buildCsp(
  nonce: string,
  options: { allowEval?: boolean } = {},
): string {
  // docs/security.md mandates `script-src 'self'`; two documented additions:
  //   - a per-request nonce for Next's inline bootstrap/flight scripts
  //   - 'unsafe-eval' only under `next dev`, whose HMR runtime evaluates strings
  const scriptSrc = options.allowEval
    ? `script-src 'self' 'nonce-${nonce}' 'unsafe-eval'`
    : `script-src 'self' 'nonce-${nonce}'`;
  return [
    "default-src 'self'",
    scriptSrc,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "connect-src 'self'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
  ].join("; ");
}

export const STATIC_SECURITY_HEADERS: Record<string, string> = {
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "X-Frame-Options": "DENY",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
};

export function withSecurityHeaders(
  response: NextResponse,
  nonce: string,
): NextResponse {
  const isDev = process.env.NODE_ENV !== "production";
  response.headers.set(
    "Content-Security-Policy",
    buildCsp(nonce, { allowEval: isDev }),
  );
  for (const [name, value] of Object.entries(STATIC_SECURITY_HEADERS)) {
    response.headers.set(name, value);
  }
  return response;
}

export function middleware(_request: NextRequest): NextResponse {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  return withSecurityHeaders(NextResponse.next(), nonce);
}

export const config = {
  matcher: "/((?!_next/static|_next/image|favicon.ico|v1|health|metrics).*)",
};
