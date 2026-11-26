import * as Cloudflare from "@alchemy.run/cloudflare";
import * as Alchemy from "alchemy";
import * as Config from "effect/Config";
import * as Effect from "effect/Effect";
import { createPublicKey } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { build } from "vite";

import { ALIAS_LABELS, PRIMARY_LABEL } from "./src/site";

type WranglerConfig = {
  name: string;
  compatibility_date: string;
  durable_objects: { bindings: { name: string; class_name: string }[] };
  vars: Record<string, string>;
};

const testedRuntime: WranglerConfig = JSON.parse(
  readFileSync(new URL("./wrangler.json", import.meta.url), "utf8"),
);

const durableObjects = Object.fromEntries(
  testedRuntime.durable_objects.bindings.map(({ name, class_name }) => [
    name,
    Cloudflare.DurableObject(class_name),
  ]),
);

// NOTE: Cloudflare's published API types predate Workers Issues, so `issues`
// cannot sit in the Worker's props literal; Alchemy forwards the key anyway.
// Every deploy uploads this whole block, and one without `issues` turns
// Issues off.
const observability = {
  enabled: true,
  issues: { enabled: true },
  logs: { enabled: true, invocationLogs: false },
};

// The board verifies passes Django signs with Parley's key. The committed
// dev pair's private half is public, so a Worker that trusts its public half
// would accept passes anyone can sign.
const devPublicKey = createPublicKey(
  readFileSync(new URL("../parley/dev-signing-key.pem", import.meta.url), "utf8"),
).export({ format: "der", type: "spki" });

function refuseDevKey(pem: string): string {
  const key = createPublicKey(pem.replaceAll("\\n", "\n"));
  if (key.export({ format: "der", type: "spki" }).equals(devPublicKey)) {
    throw new Error("BOARD_PUBLIC_KEY is the committed development key");
  }
  return pem;
}

// The client is built for one origin of the app: it asks that origin for
// passes, and tldraw checks its licence key against the board's domain.
const buildClient = ({ appOrigin, licenseKey }: { appOrigin: string; licenseKey: string }) =>
  Effect.promise(async () => {
    await build({
      configFile: fileURLToPath(new URL("./vite.config.ts", import.meta.url)),
      define: {
        __APP_ORIGIN__: JSON.stringify(appOrigin),
        __TLDRAW_LICENSE_KEY__: JSON.stringify(licenseKey),
      },
      logLevel: "warn",
    });
    return fileURLToPath(new URL("./dist", import.meta.url));
  });

export default Alchemy.Stack(
  "Board",
  { providers: Cloudflare.providers(), state: Cloudflare.state() },
  Effect.gen(function* () {
    const stage = yield* Alchemy.Stage;
    // The app's own environments, each with a Worker and Durable Objects of
    // its own. Any other stage is a preview: workers.dev only, and the
    // client asks the root domain's app for passes, which answers only the
    // board's own host, so a preview opens no board.
    const hosted = { prod: testedRuntime.name, staging: `${testedRuntime.name}-staging` }[stage];
    const rootDomain = yield* Config.String("ROOT_DOMAIN");
    const appOrigin = `https://${rootDomain}`;
    const assets = yield* buildClient({
      appOrigin,
      licenseKey: yield* Config.String("TLDRAW_LICENSE_KEY").pipe(Config.withDefault("")),
    });
    const board = yield* Cloudflare.Worker("Board", {
      name: hosted,
      // NOTE: the aliases are attached here for DNS and TLS only; the Worker
      // answers each with a 308 to the board's own host (src/site.ts).
      domain:
        hosted === undefined
          ? undefined
          : {
              name: `${PRIMARY_LABEL}.${rootDomain}`,
              aliases: ALIAS_LABELS.map((label) => `${label}.${rootDomain}`),
            },
      main: fileURLToPath(new URL("./src/index.ts", import.meta.url)),
      assets: {
        directory: assets,
        htmlHandling: "none",
        notFoundHandling: "none",
        // Every request meets the Worker first: aliases redirect, and pages
        // and files leave with the board's headers.
        runWorkerFirst: true,
      },
      compatibility: {
        date: testedRuntime.compatibility_date,
        // NOTE: Alchemy switches Workers to the new module registry unless
        // told otherwise, and the tests run the legacy one this date
        // defaults to. nodejs_compat is on by default from 2026-08-04, so
        // Alchemy leaves it out.
        flags: ["legacy_module_registry"],
      },
      observability,
      env: {
        ...durableObjects,
        ...testedRuntime.vars,
        APP_ORIGIN: appOrigin,
        ROOT_DOMAIN: rootDomain,
        BOARD_PUBLIC_KEY: Config.String("BOARD_PUBLIC_KEY").pipe(Config.map(refuseDevKey)),
      },
    });
    return { url: board.url };
  }),
);
