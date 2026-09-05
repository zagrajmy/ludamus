import { test as base } from "@playwright/test";
import { CoverageReport } from "monocart-coverage-reports";

import { collecting, coverageOptions } from "../../coverage";

// The suite's own `test`: specs import from here, not from @playwright/test,
// so every one of them lands in the client coverage report.
//
// consentSeed pre-answers the Prologue analytics banner ("declined") before
// any page script runs — the fixed bottom banner would otherwise cover the
// bottom strip of every viewport and swallow clicks suite-wide. The consent
// spec opts back into the pristine state with `test.use({ consentSeed: null })`.
export const test = base.extend<{
  clientCoverage: void;
  consentSeed: "accepted" | "declined" | null;
  seedNewContexts: void;
}>({
  consentSeed: ["declined", { option: true }],
  context: async ({ context, consentSeed }, use) => {
    if (consentSeed !== null) {
      await context.addInitScript((choice) => {
        window.localStorage.setItem("prologue.consent", choice);
      }, consentSeed);
    }
    await use(context);
  },
  // Tests that call browser.newContext() themselves (custom viewports) skip
  // the `context` fixture above, so the same seed is patched in here. The
  // browser is worker-scoped and shared, so the patch is undone after each
  // test — the next one may run with a different consentSeed.
  seedNewContexts: [
    async ({ browser, consentSeed }, use) => {
      const original = browser.newContext.bind(browser);
      browser.newContext = async (options) => {
        const context = await original(options);
        if (consentSeed !== null) {
          await context.addInitScript((choice) => {
            window.localStorage.setItem("prologue.consent", choice);
          }, consentSeed);
        }
        return context;
      };
      await use();
      browser.newContext = original;
    },
    { auto: true },
  ],
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
