import type { CoverageReportOptions } from "monocart-coverage-reports";

import path from "node:path";

const repoRoot = path.resolve(__dirname, "..", "..");

export const collecting = !!process.env.COVERAGE_FILE?.endsWith(".coverage.e2e");

export const coverageOptions: CoverageReportOptions = {
  name: "Client TypeScript",
  outputDir: path.join(repoRoot, "coverage-client"),
  reports: [["lcovonly", { file: "lcov.info" }], "console-summary"],
  entryFilter: "**/static/vite/**",
  sourceFilter: "**/client/src/**",
  sourcePath: (filePath) => {
    const marker = "client/src/";
    const at = filePath.indexOf(marker);
    return at === -1 ? filePath : `src/ludamus/client/src/${filePath.slice(at + marker.length)}`;
  },
};
