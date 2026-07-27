import { CoverageReport } from "monocart-coverage-reports";

import { collecting, coverageOptions } from "./coverage";

export default async function globalTeardown() {
  if (!collecting) return;
  const results = await new CoverageReport(coverageOptions).generate();
  if (!results?.files?.length) {
    throw new Error(
      "Client coverage is empty. The server was likely reused from a build without" +
        " inline sourcemaps — stop it and let the e2e run start its own.",
    );
  }
}
