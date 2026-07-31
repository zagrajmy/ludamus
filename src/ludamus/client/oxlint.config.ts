import { defineConfig } from "oxlint";
import baseConfig from "@hasparus/oxlint-config";

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
});
