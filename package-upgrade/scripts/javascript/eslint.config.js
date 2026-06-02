// ESLint flat config for the package-upgrade JS helper scripts.
// These are Node CommonJS scripts (require / module.exports), so we lint with
// the recommended ruleset plus Node globals. node_modules/ is ignored by default.
const js = require("@eslint/js");
const globals = require("globals");

module.exports = [
  js.configs.recommended,
  {
    files: ["**/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "commonjs",
      globals: { ...globals.node },
    },
    rules: {
      // Helper scripts intentionally keep some scaffolding vars; warn, don't error,
      // and allow the conventional `_`-prefixed throwaway.
      "no-unused-vars": [
        "warn",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_", caughtErrorsIgnorePattern: "^_" },
      ],
    },
  },
];
