import { analyzePageAccessibility } from "./helpers/a11y";
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

  test("bookmarks from another sphere's event wait in coming up", async ({ page }) => {
    await page.goto("/dashboard/");

    const comingUp = page.getByRole("region", { name: "Coming up" });
    const card = comingUp.getByRole("link", { name: /Starred Dungeon Crawl/ });
    await expect(card).toContainText("Foreign Programme");
    await expect(card).toContainText("Bookmarked · 5 spots left");
    await expect(card).toHaveAttribute(
      "href",
      /^https?:\/\/foreign\.localhost:8000\/event\/foreign-programme\/session\/\d+\/enrollment\/$/,
    );
  });

  test("coming up says where the member waits and offers a held seat to claim", async ({
    page,
  }) => {
    await page.goto("/dashboard/");

    const comingUp = page.getByRole("region", { name: "Coming up" });
    const waitlisted = comingUp.locator("article").filter({ hasText: "Waitlisted Heist" });
    await expect(waitlisted).toContainText("On the waiting list");
    await expect(waitlisted.getByRole("button")).toHaveCount(0);

    const offered = comingUp.locator("article").filter({ hasText: "Offered Duel" });
    await expect(offered).toContainText("A seat is held for you until");
    await expect(offered.getByRole("button", { name: "Claim my spot" })).toBeVisible();
  });

  test("past events list where the member has been, with the year", async ({ page }) => {
    await page.goto("/dashboard/");

    const past = page.getByRole("region", { name: "Past events" });
    const card = past.getByRole("link", { name: /Last Year's Convention/ });
    await expect(card).toBeVisible();
    await expect(card).toContainText(/\d{4}/);
  });

  test("subscribing to a sphere asks before it commits, and undoes", async ({ page }) => {
    await page.goto("/dashboard/");

    const card = page.locator("article").filter({ hasText: "Foreign Programme" });
    await card.getByRole("button", { name: "Subscribe" }).click();

    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toContainText("notify you");
    await expect(dialog.locator('[data-confirm-icon="bell-alert"]')).toBeVisible();
    await expect(dialog.locator('[data-confirm-icon="exclamation-triangle"]')).toBeHidden();
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

  test("has no critical or serious axe violations", async ({ page }) => {
    await page.goto("/dashboard/");

    await expect(page.getByRole("heading", { name: "Your dashboard" })).toBeVisible();

    await analyzePageAccessibility(page);
  });
});
