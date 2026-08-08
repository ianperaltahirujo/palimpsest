import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";

// Deliberately minimal: `react-hooks`'s newer rule set (v7) targets the
// React Compiler and carries rules (purity, immutability, use-memo, ...)
// tuned for compiler-managed code this project was never written
// against -- enabling the full "recommended" set here would be noise,
// not signal. Only the two rules that predate the compiler push
// (rules-of-hooks, exhaustive-deps) are turned on.
export default [
  { ignores: ["dist/**", "node_modules/**"] },
  js.configs.recommended,
  {
    files: ["**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      parserOptions: { ecmaFeatures: { jsx: true } },
      globals: { ...globals.browser, ...globals.es2022 },
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
      "react-refresh/only-export-components": "warn",
      "no-unused-vars": ["warn", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
    },
  },
  {
    files: ["**/*.test.{js,jsx}", "vitest.setup.js"],
    languageOptions: { globals: { ...globals.node, ...globals.browser } },
  },
];
