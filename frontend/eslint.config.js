// frontend/eslint.config.js — flat config (ESLint 10 is flat-config-only).
//
// WR-05: the package.json declares `"lint": "eslint ."` plus typescript-eslint,
// eslint-plugin-react-hooks, and eslint-plugin-react-refresh, but no config file
// existed — so `eslint .` errored out and the react-hooks rules (which catch real
// bugs like missing effect deps) never ran. This adds the standard Vite + React 19
// + TS flat config so the declared lint script actually lints.

import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  // Build output is generated — never lint it.
  { ignores: ["dist"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [
      js.configs.recommended,
      ...tseslint.configs.recommended,
      // react-refresh ships a proper flat config object.
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    // eslint-plugin-react-hooks@7's `recommended-latest` config still declares
    // `plugins: ["react-hooks"]` (legacy array form), which ESLint 10 flat config
    // rejects. Register the plugin as an object and enable the two core rules that
    // catch real bugs — rules-of-hooks and the missing-effect-deps check — directly.
    plugins: {
      "react-hooks": reactHooks,
    },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
    },
  },
  {
    // shadcn-vue/ui generated components co-locate a component with its CVA
    // variants helper (e.g. button.tsx exports both Button and buttonVariants).
    // react-refresh/only-export-components flags that pattern; downgrade it to a
    // warning for the generated ui/ dir so it doesn't fail the lint run.
    files: ["src/components/ui/**/*.{ts,tsx}"],
    rules: {
      "react-refresh/only-export-components": "warn",
    },
  },
);
