import * as Cloudflare from "@alchemy.run/cloudflare";
import * as Alchemy from "alchemy";
import { Effect, Layer } from "effect";

const stack = Alchemy.Stack(
  "Zagrajmy",
  { providers: Layer.mergeAll(Cloudflare.providers()), state: Cloudflare.state() },
  Effect.gen(function* zagrajmyStack() {
    const database = yield* Cloudflare.Hyperdrive.Connection("zagrajmy-postgres", {
      origin: Alchemy.secret("DATABASE_URL"),
    });

    const backend = yield* Cloudflare.Worker("zagrajmy-backend", {
      bindings: { DATABASE: database, SECRET_KEY: Alchemy.secret("SECRET_KEY") },
      entrypoint: "../server/src/worker.ts",
    });

    const website = yield* Cloudflare.Website.Foldkit("zagrajmy-web", {
      assets: {
        htmlHandling: "drop-trailing-slash",
        runWorkerFirst: ["/rpc", "/rpc/*", "/api/*", "/mcp", "/healthz/"],
      },
      env: { BACKEND: backend },
      rootDir: "../web",
    });

    return { backendUrl: backend.url, websiteUrl: website.url };
  })
);

export default stack;
