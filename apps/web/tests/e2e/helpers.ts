import type { Page } from "@playwright/test";

export const API_BASE = process.env.API_BASE ?? "http://127.0.0.1:8000";
export const DEV_USER = "dev-user";

export type FakeStep = {
  deltas?: string[];
  finish_reason?: string;
  fail_after?: number | null;
  delay_seconds?: number;
  ignores_cancel?: boolean;
};

export async function setFakePlan(steps: FakeStep[]): Promise<void> {
  const response = await fetch(`${API_BASE}/v1/_test/fake-plan`, {
    method: "POST",
    headers: { "content-type": "application/json", "X-Dev-User": DEV_USER },
    body: JSON.stringify({ steps }),
  });
  if (!response.ok) {
    throw new Error(`fake plan rejected with ${response.status}`);
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "X-Dev-User": DEV_USER },
  });
  if (!response.ok) {
    throw new Error(`GET ${path} failed with ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function startConversation(page: Page): Promise<string> {
  await page.goto("/");
  await page.getByRole("button", { name: "New conversation" }).click();
  await page.getByRole("link", { name: "New conversation" }).first().click();
  await page.waitForURL(/\/c\/[0-9a-f-]{36}$/);
  return new URL(page.url()).pathname.split("/").pop() ?? "";
}

export async function send(page: Page, text: string): Promise<void> {
  const composer = page.getByRole("textbox", { name: "Message" });
  await composer.fill(text);
  await composer.press("Enter");
}
