import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

import { send, setFakePlan, startConversation } from "./helpers";

test("conversation list and transcript pass axe in a real browser", async ({
  page,
}) => {
  await setFakePlan([
    { deltas: ["Accessible ", "answer"], delay_seconds: 0.02 },
  ]);
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Copilot" })).toBeVisible();

  const listResults = await new AxeBuilder({ page }).analyze();
  expect(listResults.violations).toEqual([]);

  await startConversation(page);
  await send(page, "Check accessibility");

  const assistant = page.locator(".message-bubble--assistant").first();
  await expect(assistant).toContainText("Accessible answer", {
    timeout: 20_000,
  });
  await expect(page.getByRole("button", { name: "Regenerate" })).toBeVisible();

  const transcriptResults = await new AxeBuilder({ page }).analyze();
  expect(transcriptResults.violations).toEqual([]);
});
