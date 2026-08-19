import type { Page } from "@playwright/test";

import { expect, test } from "./helpers/fixtures";

// Full announcement round trip against "Cinderpeak Game Days" (bootstrap_data.py),
// the event seeded for panel CRUD walkthroughs. The steps build on each other and
// run serially in one shared browser context; the run starts and ends with an
// empty list, so nothing is left on the public event page for other specs.
test.describe.configure({ mode: "serial" });

const EVENT = "cinderpeak-con";
const PANEL_URL = `/panel/event/${EVENT}/announcements/`;
const PUBLIC_URL = `/event/${EVENT}/`;

const TITLE = "Doors open at 9";
const TITLE_EDITED = "Doors open at 10";

// The event page is served `cache-control: private, max-age=180`, so a second
// visit inside one browser context would replay the first response. Each visit
// takes its own URL to force a real request.
function publicUrl(step: string): string {
  return `${PUBLIC_URL}?announcement-step=${step}`;
}

// Serial retries re-run the group from the top, and a failed attempt can leave
// a row behind — every later title lookup would then match two cells and fail
// strict mode. Start from an empty list instead.
async function clearAnnouncements(page: Page): Promise<void> {
  await page.goto(PANEL_URL);
  while (await page.getByRole("button", { name: "Delete" }).first().isVisible()) {
    await page.getByRole("button", { name: "Delete" }).first().click();
    // [data-confirm] opens the shared in-page dialog, not a native confirm().
    await page.getByRole("button", { name: "Confirm" }).click();
    await page.waitForURL(/\/announcements\/$/);
  }
  await expect(page.getByText("No announcements yet.")).toBeVisible();
}

test.describe("Event announcements", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Username:").fill("e2e-manager");
    await page.getByLabel("Password:").fill("e2e-manager-123");
    await page.getByRole("button", { name: /Log in/i }).click();
  });

  test("posts an announcement and shows it on the event page", async ({ page }) => {
    await clearAnnouncements(page);
    // On an empty list the header button and the empty-state CTA both read
    // "New announcement"; take the header one.
    await page.getByRole("link", { name: "New announcement" }).first().click();

    await page.getByLabel("Title").fill(TITLE);
    await page.getByLabel("Content").fill("Be early, the queue gets long.");
    await page.getByRole("button", { name: "Post announcement" }).click();

    await page.waitForURL(/\/announcements\/$/);
    await expect(page.getByRole("cell", { name: TITLE })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Published" })).toBeVisible();

    await page.goto(publicUrl("posted"));
    await expect(page.getByRole("heading", { name: "Event news" })).toBeVisible();
    await expect(page.getByRole("heading", { name: TITLE })).toBeVisible();
    await expect(page.getByText("Be early, the queue gets long.")).toBeVisible();
  });

  test("unpublishing hides it from the event page", async ({ page }) => {
    await page.goto(PANEL_URL);
    await page.getByRole("link", { name: "Edit" }).first().click();

    await page.getByLabel("Title").fill(TITLE_EDITED);
    await page.getByLabel("Published").uncheck();
    await page.getByRole("button", { name: "Save" }).click();

    await page.waitForURL(/\/announcements\/$/);
    await expect(page.getByRole("cell", { name: TITLE_EDITED })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Draft" })).toBeVisible();

    await page.goto(publicUrl("unpublished"));
    await expect(page.getByRole("heading", { name: "Event news" })).toBeHidden();
  });

  test("deletes the announcement", async ({ page }) => {
    await clearAnnouncements(page);
  });
});
