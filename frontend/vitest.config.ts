import { defineConfig } from "vitest/config";
import path from "path";

// Minimal Vitest config for Phase 11 pure-function units (footgun calc + zod cap schema).
// These are deterministic pure functions off bare numerics — no DOM, so the default `node`
// environment is sufficient (jsdom NOT required). The only thing the units need from the
// build setup is the `@/` path alias used across src/ (mirrors vite.config.ts + tsconfig paths).
export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
