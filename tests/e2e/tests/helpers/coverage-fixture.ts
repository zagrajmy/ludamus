import { test as base } from "@playwright/test";
import { CoverageReport } from "monocart-coverage-reports";

import { coverageOptions } from "../../coverage";

const collecting = !!process.env.COVERAGE_FILE;

export const test = base.extend<{ clientCoverage: void }>({
  clientCoverage: [
    async ({ page, browserName }, use) => {
      if (!collecting || browserName !== "chromium") {
        await use();
        return;
      }

      await page.coverage.startJSCoverage({ resetOnNavigation: false });
      await use();
      const entries = await page.coverage.stopJSCoverage();
      await new CoverageReport(coverageOptions).add(entries);
    },
    { auto: true },
  ],
});

export { expect } from "@playwright/test";
