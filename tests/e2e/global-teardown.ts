import { CoverageReport } from "monocart-coverage-reports";

import { coverageOptions } from "./coverage";

export default async function globalTeardown() {
  if (!process.env.COVERAGE_FILE) return;
  await new CoverageReport(coverageOptions).generate();
}
