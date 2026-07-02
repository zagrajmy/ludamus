import { expect, test } from "@playwright/test";

test.describe("Flatpages", () => {
  test("About page displays seeded content", async ({ page }) => {
    await page.goto("/page/about/");

    await expect(page.getByRole("heading", { name: "About Ludamus" })).toBeVisible();

    await expect(
      page.getByText("Ludamus is a community platform for tabletop gaming events."),
    ).toBeVisible();
    await expect(page.getByText("What we offer")).toBeVisible();
    await expect(page.getByText("Event scheduling and management")).toBeVisible();
    await expect(page.getByText("Session proposals from game masters")).toBeVisible();
    await expect(page.getByText("Our Mission")).toBeVisible();
    await expect(page.getByText("we're here to help you find your table")).toBeVisible();

    await expect(page.getByRole("link", { name: /Back to Home/ })).toBeVisible();
  });
});
