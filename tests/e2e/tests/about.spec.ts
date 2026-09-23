import { expect, test } from "./helpers/fixtures";

test.describe("About page", () => {
  test("lays out the company in plain, crawlable sections", async ({ page }) => {
    await page.goto("/about/");

    await expect(page).toHaveTitle(/About Zagrajmy/);
    await expect(page.getByRole("heading", { level: 1, name: "About Zagrajmy" })).toBeVisible();
    for (const name of [
      "What Zagrajmy does",
      "What makes Zagrajmy different",
      "Who uses Zagrajmy",
      "The team behind Zagrajmy",
      "How Zagrajmy works",
      "Key facts",
      "Frequently asked questions",
    ]) {
      await expect(page.getByRole("heading", { level: 2, name })).toBeVisible();
    }

    const facts = page.locator("dl");
    await expect(facts.getByRole("term").filter({ hasText: "Founder" })).toBeVisible();
    await expect(
      facts.getByRole("definition").filter({ hasText: "Radosław Ganczarek" }).first(),
    ).toBeVisible();
    await expect(facts.getByRole("term").filter({ hasText: "Events in Zagrajmy" })).toBeVisible();
  });

  test("the footer links to it", async ({ page }) => {
    await page.goto("/");

    await page.getByRole("contentinfo").getByRole("link", { name: "About Zagrajmy" }).click();

    await expect(page).toHaveURL(/\/about\/$/);
  });
});
