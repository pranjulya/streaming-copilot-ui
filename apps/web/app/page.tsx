"use client";

import { useMemo } from "react";

import { createConversationClient } from "../features/chat/api/client";
import { AppShell } from "../features/chat/components/AppShell";
import { ConversationList } from "../features/chat/components/ConversationList";

export default function Page() {
  const client = useMemo(() => createConversationClient(), []);
  return (
    <AppShell>
      <ConversationList client={client} />
    </AppShell>
  );
}
