import { expect, test } from "./helpers/fixtures";

// Seeded by _seed_past_archive_sphere in scripts/bootstrap_data.py: ten past
// items, one over the cards limit, across September to June 2025.
const ARCHIVE = "http://archive.localhost:8000/";

test.describe("Past archive", () => {
  test("past items over the cards limit list by month, latest three open", async ({
    page,
  }, testInfo) => {
    await page.goto(ARCHIVE);

    const events = page.locator("#events");
    await expect(events.getByRole("heading", { level: 3 })).toHaveText([
      "September 2025",
      "August 2025",
      "July 2025",
    ]);
    // Folded months stay in the page, out of sight and out of the outline.
    await expect(events.getByText("June 2025")).toBeAttached();
    await expect(events.getByText("June 2025")).toBeHidden();
    // Rows, not cards: no calendar page anywhere in the archive.
    await expect(events.locator("time")).toHaveCount(0);
    await expect(events.locator("a")).toHaveCount(10);

    const row = events.getByRole("link").filter({ hasText: "Archive Meetup Sep 28" });
    await expect(row).toBeVisible();
    await expect(row.getByText("28", { exact: true })).toBeVisible();
    await expect(row.getByText("Sun", { exact: true })).toBeVisible();
    await expect(row).toHaveAttribute("href", /archive-meetup-09-28/);

    const encounter = events.getByRole("link").filter({ hasText: "Archive Table September" });
    await expect(encounter).toHaveAttribute("href", /ARCH01/);
    await expect(encounter.getByText(/Root/)).toBeVisible();

    await testInfo.attach("past-archive.png", {
      body: await events.screenshot(),
      contentType: "image/png",
    });
  });

  test("the older months open from the fold and close again", async ({ page }) => {
    await page.goto(ARCHIVE);

    const fold = page.getByText("Show older (2)");
    await expect(page.getByText("Archive Table June")).toBeHidden();

    await fold.click();
    await expect(page.getByRole("heading", { name: "June 2025" })).toBeVisible();
    await expect(page.getByText("Archive Table June")).toBeVisible();
    await expect(fold).toBeHidden();

    await page.getByText("Hide older").click();
    await expect(page.getByText("Archive Table June")).toBeHidden();
  });
});
