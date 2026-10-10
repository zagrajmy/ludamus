import type { CoverageReportOptions } from "monocart-coverage-reports";

import path from "node:path";

const repoRoot = path.resolve(__dirname, "..", "..");

export const collecting = !!process.env.COVERAGE_FILE?.endsWith(".coverage.e2e");

export const coverageOptions: CoverageReportOptions = {
  name: "Client TypeScript",
  outputDir: path.join(repoRoot, "coverage-client"),
  reports: [["lcovonly", { file: "lcov.info" }], "console-summary"],
  // Vite's own auto-named `chunk-*.js` output (shared code it factors out
  // across entry points, e.g. a CJS/ESM interop helper) carries no sourcemap
  // back to a first-party file — there is no TS source to map to by design.
  // Parley's dependencies are the first to pull one in; excluding it here
  // keeps the real signal in global-teardown.ts's unmapped-sources check,
  // which otherwise cannot tell that gap apart from a stale/reused server.
  entryFilter: {
    "**/static/vite/assets/chunk-*.js": false,
    "**/static/vite/**": true,
  },
  sourceFilter: "**/client/src/**",
  sourcePath: (filePath) => {
    const marker = "client/src/";
    const at = filePath.indexOf(marker);
    return at === -1 ? filePath : `src/ludamus/client/src/${filePath.slice(at + marker.length)}`;
  },
};
