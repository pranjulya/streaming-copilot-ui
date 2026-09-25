import type { Metadata } from "next";
import { headers } from "next/headers";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = { title: "Copilot" };

export default async function RootLayout({
  children,
}: {
  children: ReactNode;
}) {
  // Calling headers() opts the whole app into dynamic rendering, which the per-request
  // nonce CSP in middleware.ts requires: Next.js only stamps its inline bootstrap/flight
  // scripts with the nonce when the page is rendered per request (docs/security.md §3).
  // The nonce itself is read from the forwarded request header and applied by Next.js,
  // so it only needs to be read here for app-authored inline/third-party scripts.
  await headers();
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
