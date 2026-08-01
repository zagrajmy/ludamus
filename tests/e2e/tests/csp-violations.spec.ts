import { type Page } from "@playwright/test";

import { assertNoCspViolations, installCspViolationCollector } from "./helpers/csp";
import { expect, test } from "./helpers/fixtures";

declare global {
  interface Window {
    __printCalls: number;
  }
}

// Print buttons can't be clicked for real (a print dialog would block the run),
// and a no-op stub also lets a test assert the handler actually fired.
const stubPrint = (page: Page): Promise<void> =>
  page.addInitScript(() => {
    window.__printCalls = 0;
    window.print = () => {
      window.__printCalls += 1;
    };
  });

// Proves the enforcing CSP (script-src 'self' 'nonce-…', no unsafe-inline,
// no unsafe-eval — see plan 019 and settings.CSP_POLICY) doesn't block any
// legitimate script on the pages that carry inline <script> tags or behavior
// that used to live in an inline event-handler attribute (which a nonce can
// never cover, so those became data-action/data-autosubmit + actions.ts).
//
// Each test installs the violation collector, then asserts the collected list
// is empty after the page has settled and, where relevant, after a user
// interaction that exercises the page's inline script or a delegated
// actions.ts / panel-chrome.ts / htmx handler. Interactions matter: a blocked
// handler leaves the markup intact and fails silently, so a load-only sweep
// would miss it.

test.describe("CSP enforcement doesn't break legitimate scripts", () => {
  test("public event list", async ({ page }) => {
    await installCspViolationCollector(page);

    await page.goto("/events/");
    await expect(page.getByRole("heading", { name: "Upcoming events" })).toBeVisible();

    await assertNoCspViolations(page);
  });

  test("dense event page, whose compact schedule ships its own inline script", async ({ page }) => {
    await installCspViolationCollector(page);

    // chronology/_compact_schedule.html renders only above
    // COMPACT_SCHEDULE_MIN_SESSIONS, so the regular event detail test below
    // takes the card branch and never loads this page's scroll-restore
    // script.
    await page.goto("/chronology/event/kapitularz-2025-anonymized/");
    await expect(page.getByRole("navigation", { name: "Jump to time" })).toBeVisible();

    await assertNoCspViolations(page);
  });

  test("public print page's Print button", async ({ page }) => {
    await installCspViolationCollector(page);
    await stubPrint(page);

    await page.goto("/event/kapitularz-2025-anonymized/print/");
    await page.getByRole("button", { name: "Print", exact: true }).click();

    // Was onclick="window.print()" — an attribute no nonce can cover, so the
    // button was inert under the enforcing header. Asserting the call, not
    // just the absence of a violation: a dropped data-action would be silent.
    expect(await page.evaluate(() => window.__printCalls)).toBe(1);
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
    const foldButton = page.getByRole("button", { name: "Toggle sidebar" });
    await foldButton.click();
    await expect(page.locator("html")).toHaveAttribute("data-folded", "");
    await foldButton.click();
    await page.getByRole("button", { name: "Program" }).click();

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
    // than just a blocked <script> tag) would also be caught. The rendered
    // rows are plain divs with no distinct accessible role, so the count
    // assertion stays scoped by id/class rather than getByRole/getByText.
    await page.getByRole("button", { name: "Add" }).click();
    await expect(page.locator("#durations-list .duration-item")).not.toHaveCount(0);

    await assertNoCspViolations(page);
  });
});

// Panel pages whose behavior used to live in an inline event-handler
// attribute. Each of these fails silently when blocked — the control is still
// there, it just stops doing anything — so every test drives the control and
// asserts the effect, not merely the absence of a violation.
test.describe("CSP enforcement doesn't break converted inline handlers", () => {
  test.beforeEach(async ({ page }) => {
    await installCspViolationCollector(page);
    await stubPrint(page);
    await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Username:").fill("e2e-manager");
    await page.getByLabel("Password:").fill("e2e-manager-123");
    await page.getByRole("button", { name: /Log in/i }).click();
  });

  test("proposals track filter submits its form", async ({ page }) => {
    await page.goto("/panel/event/sunhaven-festival/proposals/", {
      waitUntil: "domcontentloaded",
    });

    // "Multiple tracks" is a static option, so this doesn't depend on which
    // tracks the fixtures seed.
    await page.getByLabel("Track").selectOption("multi");

    await expect(page).toHaveURL(/[?&]track=multi/);
    await assertNoCspViolations(page);
  });

  test("timetable log room filter submits its form", async ({ page }) => {
    await page.goto("/panel/event/sunhaven-festival/timetable/log/", {
      waitUntil: "domcontentloaded",
    });

    const room = page.getByLabel("Room");
    const value = await room.locator("option").nth(1).getAttribute("value");
    await room.selectOption(value);

    await expect(page).toHaveURL(new RegExp(`[?&]space=${value}`));
    await assertNoCspViolations(page);
  });

  test("print-scope picker opens the scoped printout in a new tab", async ({ page }) => {
    await page.goto("/panel/event/kapitularz-2025-anonymized/print/", {
      waitUntil: "domcontentloaded",
    });

    const scope = page.getByLabel("Print timetable for a venue or area");
    const [popup] = await Promise.all([
      page.waitForEvent("popup"),
      scope.selectOption({ index: 1 }),
    ]);

    await expect(popup).toHaveURL(/[?&]scope=\d+/);
    await popup.close();
    // The picker resets itself so the same scope can be opened twice.
    await expect(scope).toHaveValue("");
    await assertNoCspViolations(page);
  });

  test("panel printout's Print button", async ({ page }) => {
    await page.goto("/panel/event/kapitularz-2025-anonymized/timetable/print/timetable/", {
      waitUntil: "domcontentloaded",
    });

    await page.getByRole("button", { name: "Print", exact: true }).click();

    expect(await page.evaluate(() => window.__printCalls)).toBe(1);
    await assertNoCspViolations(page);
  });
});
