import { expect, test } from "@playwright/test";

import { apiGet, send, setFakePlan, startConversation } from "./helpers";

type ConversationDetail = {
  conversation: { id: string; active_run_id: string | null };
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

test("stopping mid-stream commits a cancelled run with partial text", async ({
  page,
}) => {
  await setFakePlan([
    {
      deltas: ["alpha ", "beta ", "gamma ", "delta ", "epsilon ", "zeta "],
      delay_seconds: 0.35,
    },
  ]);
  const conversationId = await startConversation(page);
  await send(page, "Explain backpressure");

  await expect(page.getByText("alpha")).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Stop" }).click();

  await expect(page.getByRole("button", { name: "Stop" })).toHaveCount(0, {
    timeout: 15_000,
  });
  const partial = page
    .locator(".message-bubble--assistant .message-text")
    .first();
  await expect(partial).toContainText("alpha");

  await expect
    .poll(async () => {
      const detail = await apiGet<ConversationDetail>(
        `/v1/conversations/${conversationId}`,
      );
      return {
        active: detail.active_run === null,
        status: detail.messages.items.at(-1)?.status ?? "",
      };
    })
    .toEqual({ active: true, status: "cancelled" });

  const detail = await apiGet<ConversationDetail>(
    `/v1/conversations/${conversationId}`,
  );
  const assistant = detail.messages.items.filter((m) => m.role === "assistant");
  expect(assistant).toHaveLength(1);
  expect(assistant[0].content.length).toBeGreaterThan(0);
  expect(assistant[0].content.length).toBeLessThan(
    "alpha beta gamma delta epsilon zeta ".length,
  );
  await expect(page.getByText("Stopped")).toBeVisible();
});
