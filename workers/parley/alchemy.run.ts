import agents from "agents/vite";
import * as Alchemy from "alchemy";
import * as Cloudflare from "alchemy/Cloudflare";
import * as Config from "effect/Config";
import * as Effect from "effect/Effect";
import { readFileSync } from "node:fs";

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

export default Alchemy.Stack(
  "Parley",
  { providers: Cloudflare.providers(), state: Cloudflare.state() },
  Effect.gen(function* () {
    const stage = yield* Alchemy.Stage;
    const parley = yield* Cloudflare.Worker("Parley", {
      name: stage === "prod" ? testedRuntime.name : undefined,
      // NOTE: the capability cookie is SameSite=Strict, so browsers send it
      // only to a Worker on the app's own site, never to workers.dev.
      domain: stage === "prod" ? yield* Config.String("PARLEY_DOMAIN") : undefined,
      main: "./src/index.ts",
      compatibility: {
        date: testedRuntime.compatibility_date,
        // NOTE: Alchemy switches Workers to the new module registry unless
        // told otherwise, and the tests run the legacy one this date
        // defaults to. nodejs_compat is on by default from 2026-08-04, so
        // Alchemy leaves it out.
        flags: ["legacy_module_registry"],
      },
      // NOTE: Alchemy bundles with Rolldown, whose Oxc transform leaves the
      // agents' @callable() decorators in place, and workerd cannot parse
      // them. The Agents SDK plugin compiles them first.
      build: { input: { plugins: [agents()] } },
      observability,
      env: {
        ...durableObjects,
        ...testedRuntime.vars,
        ALLOWED_ORIGINS: Config.String("PARLEY_ALLOWED_ORIGINS"),
        PARLEY_PUBLIC_KEY: Config.String("PARLEY_PUBLIC_KEY"),
        PARLEY_INTERNAL_SECRET: yield* Alchemy.makeRandom("ParleyInternalSecret"),
      },
    });
    return { url: parley.url };
  }),
);
