import { expect, test } from "./helpers/fixtures";

// The root domain serves the pitch to a visitor (landing.spec.ts) and this
// page to a member. Both seeded rows it leans on — the tester's own encounter
// and the foreign sphere's published event — come from bootstrap_data.py.
test.describe("Dashboard", () => {
  test("the root domain hands a signed-in member their own page", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByRole("heading", { name: "Your dashboard" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Coming up" })).toBeVisible();
    await expect(page.getByText("Backyard Tactics Night").first()).toBeVisible();
    await expect(page.getByText("You organize this").first()).toBeVisible();
  });

  test("subscribing to a sphere asks before it commits, and undoes", async ({ page }) => {
    await page.goto("/dashboard/");

    const card = page.locator("article").filter({ hasText: "Foreign Programme" });
    await card.getByRole("button", { name: "Subscribe" }).click();

    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toContainText("notify you");
    await dialog.getByRole("button", { name: "Subscribe" }).click();

    const subscribed = page
      .locator("article")
      .filter({ hasText: "Foreign Programme" })
      .getByRole("button", { name: "Subscribed" });
    await expect(subscribed).toBeVisible();

    // Leave the account as it was found, so a re-run starts from the same
    // state the first one did.
    await subscribed.click();
    await expect(
      page
        .locator("article")
        .filter({ hasText: "Foreign Programme" })
        .getByRole("button", { name: "Subscribe" }),
    ).toBeVisible();
  });
});
