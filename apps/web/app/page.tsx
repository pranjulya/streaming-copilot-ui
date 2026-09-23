"use client";

import { useMemo } from "react";

import { ConversationClient } from "../features/chat/api/client";
import { AppShell } from "../features/chat/components/AppShell";
import { ConversationList } from "../features/chat/components/ConversationList";

export default function Page() {
  const client = useMemo(
    () =>
      new ConversationClient({
        baseUrl: process.env.NEXT_PUBLIC_API_BASE ?? "",
      }),
    [],
  );
  return (
    <AppShell>
      <ConversationList client={client} />
    </AppShell>
  );
}
