// Flat ESLint config for the browser-only TypeScript client.
// `@hasparus/eslint-config` exposes its flat config array as the default export
// of the `./the-guild` subpath (the package root only re-exports it as a named
// `theGuild` binding, so we import the subpath directly).
import hasparus from "@hasparus/eslint-config/the-guild";

export default [
  ...hasparus,
  {
    ignores: ["dist/**", "node_modules/**", "../static/**"],
  },
  {
    files: ["src/**/*.ts"],
    rules: {
      // Browser client: `console.warn`/`console.error` are legitimate runtime
      // diagnostics (e.g. clipboard API unavailable). `console.log` debug
      // output stays disallowed.
      "no-console": ["warn", { allow: ["warn", "error"] }],
    },
  },
];
