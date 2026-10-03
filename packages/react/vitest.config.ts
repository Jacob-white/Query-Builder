import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    globals: true,
    maxWorkers: 2,
    minWorkers: 1,
  },
});
