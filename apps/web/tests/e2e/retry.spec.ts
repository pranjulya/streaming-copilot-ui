import { expect, test } from "@playwright/test";

import { apiGet, send, setFakePlan, startConversation } from "./helpers";

type ConversationDetail = {
  messages: {
    items: Array<{
      role: string;
      status: string;
      content: string;
      is_visible: boolean;
    }>;
  };
  active_run: { status: string } | null;
};

test("retry after a provider failure streams a new run without duplicating the user turn", async ({
  page,
}) => {
  await setFakePlan([
    { deltas: [], fail_after: 0 },
    { deltas: ["Recovered ", "answer"], delay_seconds: 0.05 },
  ]);
  const conversationId = await startConversation(page);
  await send(page, "Try me");

  await expect(page.getByRole("button", { name: "Retry" })).toBeVisible({
    timeout: 15_000,
  });
  await page.getByRole("button", { name: "Retry" }).click();

  const assistant = page
    .locator(".message-bubble--assistant .message-text")
    .first();
  await expect(assistant).toContainText("Recovered answer", {
    timeout: 20_000,
  });

  await expect(page.getByRole("button", { name: "Regenerate" })).toBeVisible({
    timeout: 15_000,
  });
  await page.getByRole("button", { name: "Regenerate" }).click();
  await expect(page.getByRole("button", { name: "Regenerate" })).toBeVisible({
    timeout: 20_000,
  });

  const detail = await apiGet<ConversationDetail>(
    `/v1/conversations/${conversationId}`,
  );
  const users = detail.messages.items.filter(
    (message) => message.role === "user",
  );
  const visibleAssistants = detail.messages.items.filter(
    (message) => message.role === "assistant" && message.is_visible,
  );
  expect(users).toHaveLength(1);
  expect(visibleAssistants).toHaveLength(1);
  expect(visibleAssistants[0].status).toBe("complete");
  await expect(page.getByText("Still generating")).toHaveCount(0);
});
