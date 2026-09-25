import { expect, test } from "@playwright/test";

test("streams a completion and reload keeps the canonical text and ids", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "New conversation" }).click();
  await page.getByRole("link", { name: "New conversation" }).click();
  await expect(page).toHaveURL(/\/c\/[0-9a-f-]{36}$/);
  const conversationPath = new URL(page.url()).pathname;

  const composer = page.getByRole("textbox", { name: "Message" });
  await composer.fill("Explain backpressure in streaming APIs");
  await composer.press("Enter");

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
