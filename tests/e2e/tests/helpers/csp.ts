import { expect, type Page } from "@playwright/test";

// Collector for `securitypolicyviolation` DOM events, shared by the CSP specs.
// .env.e2e sets ENABLE_CSP=true so this server sends the same enforcing header
// production does, not report-only: a report-only policy never blocks anything,
// so it couldn't catch a regression.

interface CollectedViolation {
  blockedURI: string;
  violatedDirective: string;
  sourceFile: string;
  lineNumber: number;
}

declare global {
  interface Window {
    __cspViolations: CollectedViolation[];
  }
}

// Installed via addInitScript, so it can't miss an event fired during the very
// first paint.
export const installCspViolationCollector = (page: Page): Promise<void> =>
  page.addInitScript(() => {
    window.__cspViolations = [];
    document.addEventListener("securitypolicyviolation", (e) => {
      window.__cspViolations.push({
        blockedURI: e.blockedURI,
        violatedDirective: e.violatedDirective,
        sourceFile: e.sourceFile,
        lineNumber: e.lineNumber,
      });
    });
  });

export const assertNoCspViolations = async (page: Page): Promise<void> => {
  const violations = await page.evaluate(() => window.__cspViolations);
  expect(violations, JSON.stringify(violations, null, 2)).toEqual([]);
};
