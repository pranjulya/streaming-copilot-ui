"use client";

import { use, useMemo } from "react";

import { ConversationClient } from "../../../features/chat/api/client";
import { AppShell } from "../../../features/chat/components/AppShell";
import { Transcript } from "../../../features/chat/components/Transcript";

export default function ConversationPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const client = useMemo(
    () =>
      new ConversationClient({
        baseUrl: process.env.NEXT_PUBLIC_API_BASE ?? "",
      }),
    [],
  );
  return (
    <AppShell>
      <Transcript client={client} conversationId={id} />
    </AppShell>
  );
}
