import { expect, test } from "@playwright/test";

import { apiGet, send, setFakePlan, startConversation } from "./helpers";

type ConversationDetail = {
  messages: {
    items: Array<{ role: string; content: string; is_visible: boolean }>;
  };
  active_run: { status: string } | null;
};

test("a response dropped after commit does not create a second user message", async ({
  page,
}) => {
  await setFakePlan([{ deltas: ["saved ", "once"], delay_seconds: 0.05 }]);
  let dropped = false;
  await page.route("**/v1/conversations/*/responses", async (route) => {
    if (dropped) {
      await route.continue();
      return;
    }
    dropped = true;
    await route.fetch();
    await route.abort("failed");
  });

  const conversationId = await startConversation(page);
  await send(page, "Do not duplicate me");

  const assistant = page
    .locator(".message-bubble--assistant .message-text")
    .first();
  await expect(assistant).toContainText("saved once", { timeout: 20_000 });
  await expect
    .poll(async () => {
      const detail = await apiGet<ConversationDetail>(
        `/v1/conversations/${conversationId}`,
      );
      return detail.active_run === null;
    })
    .toBe(true);

  const detail = await apiGet<ConversationDetail>(
    `/v1/conversations/${conversationId}`,
  );
  const users = detail.messages.items.filter(
    (message) => message.role === "user",
  );
  expect(users).toHaveLength(1);
  expect(users[0].content).toBe("Do not duplicate me");
  await expect(page.locator(".message-bubble--user")).toHaveCount(1);
});
