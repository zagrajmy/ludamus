import { type Page } from "@playwright/test";

import { expect, test } from "./helpers/fixtures";

const EVENT_URL = "/event/autumn-open/";
// The dense seeded event: the only one over the compact-schedule threshold,
// so the only one that offers a second layout to switch to.
const DENSE_EVENT_URL = "/event/kapitularz-2025-anonymized/";
const MEGA = "Mega Strategy Lab";
const NEON = "Przygoda w Mieście Neonów";
// Seeded with no participants limit: the drop-in the enrollment filter leaves out.
const COZY = "Cozy Storytellers Circle";

const card = (page: Page, title: string) =>
  page.getByRole("link", { name: `Open details for ${title}` });

// Set after load; a full navigation would wipe it, an htmx swap keeps it.
const markPage = (page: Page) =>
  page.evaluate(() => {
    (globalThis as unknown as { __sameDocument?: boolean }).__sameDocument = true;
  });

const stayedOnPage = (page: Page) =>
  page.evaluate(
    () => (globalThis as unknown as { __sameDocument?: boolean }).__sameDocument === true,
  );

const enrollmentOnly = (page: Page) => page.getByRole("checkbox", { name: "Only with enrollment" });

test.describe("Event schedule views", () => {
  test("the view switcher offers nothing when the schedule has one layout", async ({ page }) => {
    await page.goto(EVENT_URL);

    await expect(page.getByRole("tablist", { name: "Schedule view" })).toHaveCount(0);
  });

  test("the rooms tab swaps the layout in without leaving the page", async ({ page }) => {
    await page.goto(DENSE_EVENT_URL);
    await markPage(page);

    await page.getByRole("tab", { name: "Rooms" }).click();

    await expect(page.locator(".room-lanes").first()).toBeVisible();
    await expect(page).toHaveURL(/\?view=rooms$/);
    expect(await stayedOnPage(page)).toBe(true);
  });

  test("the grid offers sideways scrollbars on both edges", async ({ page }) => {
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);
    const head = page.locator("[data-room-lanes-head]").first();
    const foot = page.locator("[data-room-lanes-foot]").first();
    const body = page.locator("[data-room-lanes-scroll]").first();

    // Real scrollers — that is what puts a scrollbar at the top and the
    // bottom edge for mouse users. The body's own scrollbar yields to the
    // foot, which pins to the viewport.
    for (const handle of [head, foot]) {
      await expect(handle).toHaveCSS("overflow-x", "auto");
    }
    await expect(body).toHaveCSS("scrollbar-width", "none");

    // Targets derived from the actual overflow, so a shrunken fixture fails
    // on this precondition instead of an opaque clamped-scroll poll timeout.
    const budget = (handle: typeof head) =>
      handle.evaluate((el) => el.scrollWidth - el.clientWidth);
    const max = Math.min(await budget(head), await budget(foot));
    expect(max).toBeGreaterThanOrEqual(300);
    const far = Math.floor(max / 2);
    const near = Math.floor(max / 4);

    // Dragging either handle pans the grid, and the grid drags both along.
    await head.evaluate((el, left) => {
      el.scrollLeft = left;
    }, far);
    await expect.poll(() => body.evaluate((el) => el.scrollLeft)).toBe(far);
    await expect.poll(() => foot.evaluate((el) => el.scrollLeft)).toBe(far);

    await foot.evaluate((el, left) => {
      el.scrollLeft = left;
    }, near);
    await expect.poll(() => body.evaluate((el) => el.scrollLeft)).toBe(near);
    await expect.poll(() => head.evaluate((el) => el.scrollLeft)).toBe(near);
  });
});

test.describe("Enrollment filter", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(EVENT_URL);
    await page.getByRole("button", { name: "Filters" }).click();
  });

  test("narrows the schedule to the sessions that take sign-up", async ({ page }) => {
    await expect(page.getByRole("link", { name: /^Open details for / })).toHaveCount(3);
    await markPage(page);

    await enrollmentOnly(page).check();

    await expect(card(page, MEGA)).toBeVisible();
    await expect(card(page, NEON)).toBeVisible();
    await expect(card(page, COZY)).toBeHidden();
    // A filter, not a view: the URL mirror is a replaceState, so no request
    // goes out and nothing reloads.
    await expect.poll(() => new URL(page.url()).searchParams.get("enrollment")).toBe("1");
    expect(new URL(page.url()).pathname).toBe(EVENT_URL);
    expect(await stayedOnPage(page)).toBe(true);
  });

  test("clearing its chip brings the whole schedule back", async ({ page }) => {
    await enrollmentOnly(page).check();
    await expect(card(page, COZY)).toBeHidden();

    await page.getByRole("button", { name: "Remove filter" }).click();

    await expect(card(page, COZY)).toBeVisible();
    await expect(enrollmentOnly(page)).not.toBeChecked();
  });

  test("search still filters the sessions it left on screen", async ({ page }) => {
    await enrollmentOnly(page).check();

    await page.getByRole("textbox", { name: "Search sessions..." }).fill("mega");

    await expect(card(page, MEGA)).toBeVisible();
    await expect(card(page, NEON)).toBeHidden();
  });
});
