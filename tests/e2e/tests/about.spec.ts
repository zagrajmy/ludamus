import { expect, test } from "./helpers/fixtures";

const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:8000";
const EMPTY_SPHERE = "http://another.localhost:8000";

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
    await expect(facts.getByRole("term").filter({ hasText: "Founders" })).toBeVisible();
    await expect(
      facts
        .getByRole("definition")
        .filter({ hasText: "Radosław Ganczarek, Piotr Monwid-Olechnowicz" })
        .first(),
    ).toBeVisible();
    await expect(facts.getByRole("term").filter({ hasText: "Events in Zagrajmy" })).toBeVisible();
  });

  test("the footer links to it", async ({ page }) => {
    await page.goto("/");

    await page.getByRole("contentinfo").getByRole("link", { name: "About Zagrajmy" }).click();

    await expect(page).toHaveURL(/\/about\/$/);
  });

  test("a convention's footer links straight to the root domain's copy", async ({ page }) => {
    // The page is about Zagrajmy, so it lives on zagrajmy.net alone; linking
    // there directly spares every click a permanent-redirect hop.
    await page.goto(`${EMPTY_SPHERE}/`);

    const about = page.getByRole("contentinfo").getByRole("link", { name: "About Zagrajmy" });
    await expect(about).toHaveAttribute("href", new URL("/about/", BASE_URL).href);
  });
});
