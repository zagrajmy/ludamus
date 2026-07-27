import { test as base } from "@playwright/test";
import { CoverageReport } from "monocart-coverage-reports";

import { collecting, coverageOptions } from "../../coverage";

// The suite's own `test`: specs import from here, not from @playwright/test,
// so every one of them lands in the client coverage report.
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
