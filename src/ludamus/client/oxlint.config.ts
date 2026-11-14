import { defineConfig } from "oxlint";
import { fileURLToPath } from "node:url";
import baseConfig from "@hasparus/oxlint-config";

const tailwindEntryPoint = fileURLToPath(new URL("src/index.css", import.meta.url));

export default defineConfig({
  // TODO: drop the typeAware override to enable @hasparus/oxlint-config's
  // type-aware rules; the client has ~185 findings (15 errors) to fix first.
  extends: [baseConfig, { options: { typeAware: false } }],
  ignorePatterns: ["dist", "node_modules", "../static", "*.cjs"],
  overrides: [
    {
      files: ["src/**/*.ts"],
      rules: {
        "no-console": ["warn", { allow: ["warn", "error"] }],
      },
    },
  ],
  settings: {
    "better-tailwindcss": {
      detectComponentClasses: true,
      entryPoint: tailwindEntryPoint,
    },
  },
});
