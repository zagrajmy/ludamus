import type { FullConfig } from "@playwright/test";

import { CoverageReport } from "monocart-coverage-reports";

import { collecting, coverageOptions } from "./coverage";

// Every worker appends raw V8 data to the same cache; one report at the end
// merges it into the lcov Codecov reads alongside the Python coverage. A
// bundle that kept its own path never found its sourcemap, and uploading it
// would report coverage against a file that does not exist in the repo.
export default async function globalTeardown(config: FullConfig) {
  if (!collecting) return;
  const files = (await new CoverageReport(coverageOptions).generate())?.files ?? [];
  const unmapped = files.filter((file) => !file.sourcePath.startsWith("src/ludamus/client/src/"));
  if (unmapped.length) {
    throw new Error(
      `Client coverage did not reach the TypeScript sources (${files.length} files,` +
        ` ${unmapped.length} unmapped). The server was likely reused from a build without` +
        " inline sourcemaps — stop it and let the e2e run start its own.",
    );
  }
  // A filtered local run can legitimately touch no chromium test, and so can a
  // single shard: V8 coverage comes from chromium only, and --shard splits by
  // test count with no regard for project. Only a whole-suite CI run, whose
  // output is what gets uploaded, must produce something.
  if (!files.length && process.env.CI && !config.shard) {
    throw new Error(
      "Client coverage came back empty for a full CI run; no chromium test recorded any.",
    );
  }
}
