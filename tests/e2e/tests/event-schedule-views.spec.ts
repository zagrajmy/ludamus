import { type Page } from "@playwright/test";

import { expect, test } from "./helpers/fixtures";

const EVENT_URL = "/event/autumn-open/";
const MEGA = "Mega Strategy Lab";
const NEON = "Przygoda w Mieście Neonów";
// Seeded with no participants limit: the drop-in the enrollment view leaves out.
const COZY = "Cozy Storytellers Circle";

const card = (page: Page, title: string) => page.locator(".session", { hasText: title });

// Set after load; a full navigation would wipe it, an htmx swap keeps it.
const markPage = (page: Page) =>
  page.evaluate(() => {
    (globalThis as unknown as { __sameDocument?: boolean }).__sameDocument = true;
  });

const stayedOnPage = (page: Page) =>
  page.evaluate(
    () => (globalThis as unknown as { __sameDocument?: boolean }).__sameDocument === true,
  );

test.describe("Event schedule views", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(EVENT_URL);
  });

  test("the enrollment tab swaps in only the sessions that take sign-up", async ({ page }) => {
    await expect(page.locator(".session")).toHaveCount(3);
    await markPage(page);

    await page.getByRole("tab", { name: "Enrollment" }).click();

    await expect(card(page, MEGA)).toBeVisible();
    await expect(card(page, NEON)).toBeVisible();
    await expect(card(page, COZY)).toHaveCount(0);
    await expect(page).toHaveURL(/\?view=enrollment$/);
    expect(await stayedOnPage(page)).toBe(true);
  });

  test("the list tab brings the whole schedule back", async ({ page }) => {
    await page.getByRole("tab", { name: "Enrollment" }).click();
    await expect(page.locator(".session")).toHaveCount(2);
    await markPage(page);

    await page.getByRole("tab", { name: "List" }).click();

    await expect(page.locator(".session")).toHaveCount(3);
    await expect(page).toHaveURL(EVENT_URL);
    expect(await stayedOnPage(page)).toBe(true);
  });

  test("search still filters the sessions the swap brought in", async ({ page }) => {
    await page.getByRole("tab", { name: "Enrollment" }).click();
    await expect(page.locator(".session")).toHaveCount(2);

    await page.locator("#session-filter").fill("mega");

    await expect(card(page, MEGA)).toBeVisible();
    await expect(card(page, NEON)).toBeHidden();
  });
});
