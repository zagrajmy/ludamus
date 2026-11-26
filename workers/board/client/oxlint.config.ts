import baseConfig from "@hasparus/oxlint-config";
import { fileURLToPath } from "node:url";
import { defineConfig } from "oxlint";

// The site's lint rules (src/ludamus/client/oxlint.config.ts), for the board
// app's client. The Worker beside it keeps the repository's defaults, as
// Parley's does.
const tailwindEntryPoint = fileURLToPath(new URL("src/app.css", import.meta.url));

export default defineConfig({
  extends: [baseConfig, { options: { typeAware: false } }],
  ignorePatterns: ["dist", "node_modules"],
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
