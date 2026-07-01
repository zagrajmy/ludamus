import { expect, test } from "@playwright/test";

test.describe("Print materials", () => {
  test("panel print-materials page lists scope controls", async ({ page }) => {
    await page.goto("/panel/event/kapitularz-print/print-materials/");

    await expect(page.getByRole("heading", { name: "Print Materials" })).toBeVisible();
    await expect(page.getByText("Kapitularz Print Test")).toBeVisible();

    const links = page.getByRole("link").filter({ hasText: /Whole event|Print/ });
    await expect(links.first()).toBeVisible();
  });

  test("print page for the whole event renders the timetable", async ({ page }) => {
    await page.goto("/panel/event/kapitularz-print/print/timetable/");

    await expect(page.getByText("Kapitularz Print Test")).toBeVisible();
    await expect(page.locator("table").first()).toBeVisible();
  });

  test("print page for a single space scope filters to that room", async ({ page }) => {
    await page.goto("/panel/event/kapitularz-print/venues/");

    const roomLink = page.getByRole("link", { name: "Print Room 1" }).first();
    await roomLink.click();

    await expect(page).toHaveURL(/\/print\/timetable\/\?scope=\d+/);
    await expect(page.getByText("Print Room 1")).toBeVisible();
  });
});
