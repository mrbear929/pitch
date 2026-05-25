module.exports = {
  root: true,
  parser: "@typescript-eslint/parser",
  parserOptions: { ecmaVersion: 2020, sourceType: "module" },
  plugins: ["@typescript-eslint"],
  extends: ["eslint:recommended", "plugin:@typescript-eslint/recommended"],
  rules: {
    "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
    "@typescript-eslint/no-explicit-any": "warn",
    "no-constant-condition": ["error", { checkLoops: false }],
  },
  env: { node: true, browser: true, jest: true },
  ignorePatterns: ["main.js", "node_modules", "tests/__mocks__"],
};
