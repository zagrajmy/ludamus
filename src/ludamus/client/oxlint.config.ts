import { defineConfig } from "oxlint";
import { fileURLToPath } from "node:url";
import baseConfig from "@hasparus/oxlint-config";

const tailwindEntryPoint = fileURLToPath(new URL("src/index.css", import.meta.url));

export default defineConfig({
  extends: [baseConfig],
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
    "better-tailwindcss": { entryPoint: tailwindEntryPoint },
  },
});
