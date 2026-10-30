import path from "node:path";

import { Option, Predicate, Schema } from "effect";

import { harnessPaths } from "./paths.ts";

const ConfigModule = Schema.Struct({
  default: Schema.Record(Schema.String, Schema.Unknown),
});

const loaded = Schema.decodeUnknownSync(ConfigModule)(
  await import(harnessPaths.playwrightConfig)
);

const nested = Option.liftPredicate(loaded.default.default, Predicate.isObject);

const base = Option.match(nested, {
  onNone: () => loaded.default,
  onSome: (inner) =>
    Schema.decodeUnknownSync(ConfigModule.fields.default)(inner),
});

const resultsDirectory =
  process.env.E2E_RESULTS_DIR ??
  path.join(harnessPaths.results, "e2e", "adhoc");

export default {
  ...base,
  globalSetup: path.join(harnessPaths.e2e, "global-setup.ts"),
  globalTeardown: path.join(harnessPaths.e2e, "global-teardown.ts"),
  outputDir: path.join(resultsDirectory, "artifacts"),
  reporter: [
    ["line"],
    ["json", { outputFile: path.join(resultsDirectory, "report.json") }],
  ],
  testDir: harnessPaths.specs,
  webServer: undefined,
};
