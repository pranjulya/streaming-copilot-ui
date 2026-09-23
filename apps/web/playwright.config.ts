import { defineConfig } from "@playwright/test";

const API_PORT = 8000;
const WEB_PORT = 3100;

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: `uv run --project ../../services/api uvicorn app.main:create_app --factory --app-dir ../../services/api --host 127.0.0.1 --port ${API_PORT}`,
      url: `http://127.0.0.1:${API_PORT}/health/live`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        APP_ENV: "development",
        DATABASE_URL:
          process.env.TEST_DATABASE_URL ??
          "postgresql+asyncpg://copilot:copilot@127.0.0.1:5433/copilot",
      },
    },
    {
      command: `pnpm next dev --hostname 127.0.0.1 --port ${WEB_PORT}`,
      url: `http://127.0.0.1:${WEB_PORT}`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
