"use client";

import { use, useMemo } from "react";

import { createConversationClient } from "../../../features/chat/api/client";
import { AppShell } from "../../../features/chat/components/AppShell";
import { Transcript } from "../../../features/chat/components/Transcript";

export default function ConversationPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const client = useMemo(() => createConversationClient(), []);
  return (
    <AppShell>
      <Transcript client={client} conversationId={id} />
    </AppShell>
  );
}
