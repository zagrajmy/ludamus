import { CoverageReport } from "monocart-coverage-reports";

import { coverageOptions } from "./coverage";

export default function globalSetup() {
  if (!process.env.COVERAGE_FILE) return;
  new CoverageReport(coverageOptions).cleanCache();
}
