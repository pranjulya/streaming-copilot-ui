"use client";

import Link from "next/link";
import type { ReactNode } from "react";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="app-shell">
      <header className="app-header">
        <Link href="/" className="app-title">
          Copilot
        </Link>
      </header>
      <main className="app-main">{children}</main>
      <div role="status" aria-live="polite" className="live-region" />
    </div>
  );
}
