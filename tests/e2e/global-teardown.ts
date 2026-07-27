import { CoverageReport } from "monocart-coverage-reports";

import { collecting, coverageOptions } from "./coverage";

// Every worker appends raw V8 data to the same cache; one report at the end
// merges it into the lcov Codecov reads alongside the Python coverage. A
// bundle that kept its own path never found its sourcemap, and uploading it
// would report coverage against a file that does not exist in the repo.
export default async function globalTeardown() {
  if (!collecting) return;
  const files = (await new CoverageReport(coverageOptions).generate())?.files ?? [];
  const unmapped = files.filter((file) => !file.sourcePath.startsWith("src/ludamus/client/src/"));
  // A filtered local run can legitimately touch no chromium test; only CI,
  // which uploads what comes out, needs an empty report to be an error.
  if (unmapped.length || (!files.length && process.env.CI)) {
    throw new Error(
      `Client coverage did not reach the TypeScript sources (${files.length} files,` +
        ` ${unmapped.length} unmapped). The server was likely reused from a build without` +
        " inline sourcemaps — stop it and let the e2e run start its own.",
    );
  }
}
