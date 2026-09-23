import { expect, test } from "@playwright/test";

import { apiGet, send, setFakePlan, startConversation } from "./helpers";

type ConversationDetail = {
  messages: {
    items: Array<{ role: string; content: string; is_visible: boolean }>;
  };
  active_run: { status: string } | null;
};

test("a dropped connection recovers from the event cursor without duplicating text", async ({
  page,
  context,
}) => {
  await setFakePlan([
    {
      deltas: [
        "one ",
        "two ",
        "three ",
        "four ",
        "five ",
        "six ",
        "seven ",
        "eight ",
      ],
      delay_seconds: 0.3,
    },
  ]);
  const conversationId = await startConversation(page);
  await send(page, "Resume please");
  await expect(page.getByText("one")).toBeVisible({ timeout: 15_000 });

  await context.setOffline(true);
  await page.waitForTimeout(800);
  await context.setOffline(false);

  await expect(page.getByText("eight")).toBeVisible({ timeout: 30_000 });
  await expect
    .poll(
      async () => {
        const detail = await apiGet<ConversationDetail>(
          `/v1/conversations/${conversationId}`,
        );
        return detail.active_run === null;
      },
      { timeout: 30_000 },
    )
    .toBe(true);

  const detail = await apiGet<ConversationDetail>(
    `/v1/conversations/${conversationId}`,
  );
  const assistant = detail.messages.items.filter(
    (message) => message.role === "assistant" && message.is_visible,
  );
  expect(assistant).toHaveLength(1);
  for (const word of ["one", "three", "eight"]) {
    const occurrences = assistant[0].content.split(word).length - 1;
    expect(occurrences).toBe(1);
  }
  await page.reload();
  await expect(
    page.locator(".message-bubble--assistant .message-text").first(),
  ).toContainText("eight");
});
