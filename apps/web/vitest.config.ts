import { defineConfig } from "vitest/config";

// The ambient shell can export NODE_ENV=production. React then resolves its
// production build, where act() is undefined, and Vite treats node: builtins
// as browser-incompatible, so every component test fails before it runs. Pin
// the test env here, where it is read, so the suite no longer depends on the
// invoking shell. Next.js types NODE_ENV as readonly.
(process.env as Record<string, string>).NODE_ENV = "test";

export default defineConfig({
  oxc: { jsx: { runtime: "automatic" } },
  test: { environment: "node" },
});
