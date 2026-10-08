import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import regexp from "eslint-plugin-regexp";

export default tseslint.config(
  { ignores: ["dist/**", "node_modules/**", "tests/**"] },
  { linterOptions: { reportUnusedDisableDirectives: "warn" } },
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.{ts,tsx}"],
    plugins: { "react-hooks": reactHooks, regexp },
    rules: {
      "@typescript-eslint/no-explicit-any": "error",
      // Baseline: existing unused symbols are warnings, ratcheted by `--max-warnings` in the
      // lint script. Prefix with `_` to mark intentionally unused arguments/variables.
      "@typescript-eslint/no-unused-vars": [
        "warn",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_", caughtErrors: "none" },
      ],
      // Guards against polynomial/exponential ReDoS (CodeQL js/polynomial-redos).
      "regexp/no-super-linear-backtracking": "error",
      "regexp/no-super-linear-move": "error",
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
    },
  },
);
