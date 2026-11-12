import { cloudflareTest } from "@cloudflare/vitest-pool-workers";
import agents from "agents/vite";
import { createPublicKey } from "node:crypto";
import { readFileSync } from "node:fs";
import { defineConfig } from "vitest/config";

// The committed dev pair: tests sign passes with its private half, so the
// Worker under test trusts its public half.
const devSigningKey = readFileSync(new URL("./dev-signing-key.pem", import.meta.url), "utf8");

export default defineConfig({
  test: {
    // NOTE: the Workers pool runs no V8 inspector, so coverage is Istanbul's.
    coverage: { include: ["src/**"], provider: "istanbul", reporter: ["text-summary", "text"] },
  },
  plugins: [
    agents(),
    cloudflareTest({
      miniflare: {
        bindings: {
          PARLEY_PUBLIC_KEY: createPublicKey(devSigningKey)
            .export({ format: "pem", type: "spki" })
            .toString(),
          TEST_SIGNING_KEY: devSigningKey,
        },
      },
      wrangler: { configPath: "./wrangler.json" },
    }),
  ],
});
