import { cloudflareTest } from "@cloudflare/vitest-pool-workers";
import { createPublicKey } from "node:crypto";
import { readFileSync } from "node:fs";
import { defineConfig } from "vitest/config";

// The dev pair the app signs passes with on laptops; Parley commits it.
const devSigningKey = readFileSync(
  new URL("../parley/dev-signing-key.pem", import.meta.url),
  "utf8",
);

export default defineConfig({
  plugins: [
    cloudflareTest({
      miniflare: {
        bindings: {
          BOARD_PUBLIC_KEY: createPublicKey(devSigningKey)
            .export({ format: "pem", type: "spki" })
            .toString(),
          TEST_SIGNING_KEY: devSigningKey,
        },
      },
      wrangler: { configPath: "./wrangler.json" },
    }),
  ],
});
