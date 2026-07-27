import type { CoverageReportOptions } from "monocart-coverage-reports";

import path from "node:path";

const repoRoot = path.resolve(__dirname, "..", "..");

export const coverageOptions: CoverageReportOptions = {
  name: "Client TypeScript",
  outputDir: path.join(repoRoot, "coverage-client"),
  reports: [["lcovonly", { file: "lcov.info" }]],
  entryFilter: (entry: { url: string }) => entry.url.includes("/static/vite/"),
  sourceFilter: (sourcePath: string) => sourcePath.includes("client/src/"),
  sourcePath: (filePath: string) => {
    const marker = "client/src/";
    const at = filePath.indexOf(marker);
    return at === -1 ? filePath : `src/ludamus/client/src/${filePath.slice(at + marker.length)}`;
  },
};
