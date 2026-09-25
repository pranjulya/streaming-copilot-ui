import { expect, test } from "@playwright/test";

import { send, setFakePlan, startConversation } from "./helpers";

test("streams a completion and reload keeps the canonical text and ids", async ({
  page,
}) => {
  await setFakePlan([
    {
      deltas: [
        "This is the local fake provider. ",
        "Set XAI_API_KEY to stream real model output.",
      ],
      delay_seconds: 0.02,
    },
  ]);
  await startConversation(page);
  const conversationPath = new URL(page.url()).pathname;

  await send(page, "Explain backpressure in streaming APIs");

  const assistantBubble = page.locator(".message-bubble--assistant").first();
  await expect(assistantBubble).toContainText(
    "This is the local fake provider",
    {
      timeout: 20_000,
    },
  );
  await expect(assistantBubble).toContainText(
    "Set XAI_API_KEY to stream real model output.",
  );

  const streamedText = await assistantBubble
    .locator(".message-text")
    .innerText();
  expect(streamedText).toContain("This is the local fake provider");

  await page.reload();
  await expect(page).toHaveURL(new RegExp(`${conversationPath}$`));
  const reloaded = page.locator(".message-bubble--assistant").first();
  await expect(reloaded).toContainText("This is the local fake provider");
  const canonicalText = await reloaded.locator(".message-text").innerText();
  expect(canonicalText).toContain(
    "Set XAI_API_KEY to stream real model output.",
  );

  const userBubbles = page.locator(".message-bubble--user");
  await expect(userBubbles).toHaveCount(1);
  await expect(page.locator(".status-text")).toHaveText("");
});
