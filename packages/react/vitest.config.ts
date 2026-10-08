import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    // Exposes global.gc so heap-growth leak guards can force a collection before measuring.
    execArgv: ["--expose-gc"],
    maxWorkers: 2,
    minWorkers: 1,
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      reporter: ["text-summary", "lcov"],
      // Floors set just under the measured values; raise them as coverage improves.
      thresholds: {
        statements: 99,
        branches: 96,
        functions: 99,
        lines: 99,
      },
    },
  },
});
