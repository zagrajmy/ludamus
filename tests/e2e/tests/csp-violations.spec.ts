import { expect, test, type Page } from "@playwright/test";

// Proves the enforcing CSP (script-src 'self' 'nonce-…', no unsafe-inline,
// no unsafe-eval — see plan 019 and settings.CSP_POLICY) doesn't block any
// legitimate script on the pages that carry inline <script> tags or htmx
// hx-on-turned-data-action behavior. .env.e2e sets ENABLE_CSP=true so this
// server actually sends the same header production does, not report-only:
// a report-only policy never blocks anything, so it couldn't catch a
// regression here.
//
// Each page installs a collector for the `securitypolicyviolation` DOM
// event before any script runs (via addInitScript, so it can't miss an
// event fired during the very first paint), then asserts the collected
// list is empty after the page has settled and, where relevant, after a
// user interaction that exercises the page's inline script or delegated
// panel-chrome.ts / htmx behavior.

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

const installCspViolationCollector = (page: Page): Promise<void> =>
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

const assertNoCspViolations = async (page: Page): Promise<void> => {
  const violations = await page.evaluate(() => window.__cspViolations);
  expect(violations, JSON.stringify(violations, null, 2)).toEqual([]);
};

test.describe("CSP enforcement doesn't break legitimate scripts", () => {
  test("public event list", async ({ page }) => {
    await installCspViolationCollector(page);

    await page.goto("/events/");
    await expect(page.getByRole("heading", { name: "Upcoming events" })).toBeVisible();

    await assertNoCspViolations(page);
  });

  test("event detail page, including opening a session modal", async ({ page }) => {
    await installCspViolationCollector(page);

    await page.goto("/event/autumn-open/");
    await expect(page.getByRole("heading", { name: "Autumn Open Playtest" })).toBeVisible();

    // Exercises client-side JS (modal open, htmx/panel-chrome-adjacent
    // interactivity) rather than just the initial paint.
    await page.getByRole("link", { name: "Open details for Mega Strategy Lab" }).click();
    await expect(page.getByRole("dialog", { name: "Mega Strategy Lab" })).toBeVisible();

    await assertNoCspViolations(page);
  });

  test("panel dashboard, sidebar/category chrome, and a CFP-edit page with inline scripts", async ({
    page,
  }) => {
    await installCspViolationCollector(page);

    // Live login (as panel.spec.ts does): panel access is per-event manager
    // status, not just Django staff/superuser, and no storageState fixture
    // is seeded for the manager role.
    await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Username:").fill("e2e-manager");
    await page.getByLabel("Password:").fill("e2e-manager-123");
    await page.getByRole("button", { name: /Log in/i }).click();

    await page.goto("/panel/", { waitUntil: "domcontentloaded" });
    await expect(page).toHaveURL(/\/panel\/event\/[\w-]+\//);
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

    // Exercise panel-chrome.ts's delegated data-action listeners (the
    // hx-on: -> data-action conversion this plan's Finding 1 depends on
    // staying eval-free): fold the sidebar, then a category toggle.
    await page.locator("#sidebarFoldBtn").click();
    await expect(page.locator("html")).toHaveAttribute("data-folded", "");
    await page.locator("#sidebarFoldBtn").click();
    await page.locator('[data-cat="program"] [data-action="toggle-category"]').click();

    await assertNoCspViolations(page);

    // panel/cfp-edit.html: three inline <script> tags on one page (duration
    // add/remove, the window.__fieldPickerI18n data blob, and the picker
    // script that reads it) — the densest concentration of nonce'd scripts
    // in the app. domcontentloaded, not the default "load": Firefox
    // occasionally never fires "load" for panel pages in this environment
    // (same quirk panel.spec.ts's login goto already works around) and
    // that's unrelated to CSP — the violation collector only needs the
    // scripts to have run, not every subresource (e.g. the Google Fonts
    // stylesheet) to have finished.
    await page.goto("/panel/event/frostfire-con/cfp/rpg-proposals/", {
      waitUntil: "domcontentloaded",
    });
    await expect(page.getByRole("heading", { name: "Configure Category" })).toBeVisible();

    // Exercise the duration-list inline script so a blocked handler (rather
    // than just a blocked <script> tag) would also be caught.
    await page.locator("#add-duration-btn").click();
    await expect(page.locator("#durations-list .duration-item")).not.toHaveCount(0);

    await assertNoCspViolations(page);
  });
});
