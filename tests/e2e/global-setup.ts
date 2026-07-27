import { CoverageReport } from "monocart-coverage-reports";

import { collecting, coverageOptions } from "./coverage";

export default function globalSetup() {
  if (collecting) new CoverageReport(coverageOptions).cleanCache();
}
