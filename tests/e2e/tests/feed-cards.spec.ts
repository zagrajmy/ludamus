import { type Page } from "@playwright/test";

import { expect, test } from "./helpers/fixtures";

// Seeded by _seed_feed_cards_sphere in scripts/bootstrap_data.py. The feed
// runs in English here, so the page reads "oct", "Thu" where Polish reads
// "paź", "Czw"; CSS sets the page in capitals, the text stays as Django
// wrote it, hence the case-insensitive matches.
const FEED = "http://feed.localhost:8000/";

const calendarPage = (page: Page, title: string) =>
  page.locator("#events").getByRole("link").filter({ hasText: title }).locator("time");

test.describe("Calendar page on feed cards", () => {
  test("an event across a month boundary shows its range, not its start alone", async ({
    page,
  }, testInfo) => {
    await page.goto(FEED);

    const leaf = calendarPage(page, "Harvest Convention");
    await expect(leaf).toHaveAttribute("datetime", /^2031-10-30T10:00:00/);
    // The page is drawn for the eye; screen readers get the whole range.
    await expect(leaf.getByText("Oct 30, 2031, 10 a.m. – Nov 1, 2031, 6 p.m.")).toBeAttached();
    await expect(leaf.getByText(/^oct–nov$/i)).toBeVisible();
    await expect(leaf.getByText("30–1", { exact: true })).toBeVisible();
    await expect(leaf.getByText(/^thu–sat$/i)).toBeVisible();
    await expect(leaf.getByText("10:00", { exact: true })).toBeVisible();

    await testInfo.attach("feed-cards.png", {
      body: await page.locator("#events").screenshot(),
      contentType: "image/png",
    });
  });

  test("a single day outside this year carries the year in its band", async ({ page }) => {
    await page.goto(FEED);

    const leaf = calendarPage(page, "Sunday Pub Session");
    await expect(leaf.getByText(/^nov 2031$/i)).toBeVisible();
    await expect(leaf.getByText("9", { exact: true })).toBeVisible();
    await expect(leaf.getByText(/^sun$/i)).toBeVisible();
    await expect(leaf.getByText("13:00", { exact: true })).toBeVisible();
  });

  test("an evening that runs past midnight stays one day", async ({ page }) => {
    await page.goto(FEED);

    const leaf = calendarPage(page, "Late Night Tactics");
    await expect(leaf.getByText("4", { exact: true })).toBeVisible();
    await expect(leaf.getByText(/^tue$/i)).toBeVisible();
    await expect(leaf.getByText("4–5", { exact: true })).toHaveCount(0);
  });

  test("a running event says so where its hour would be", async ({ page }) => {
    await page.goto(FEED);

    await expect(
      calendarPage(page, "Running Marathon").getByText("ongoing", { exact: true }),
    ).toBeVisible();
  });

  test("a past encounter counts who came, not the spots left", async ({ page }) => {
    await page.goto(FEED);

    const card = page.locator("#events").getByRole("link").filter({ hasText: "Old Tuesday Table" });
    await expect(card.getByText("0 attending")).toBeVisible();
    await expect(card.getByText(/spots? left/)).toHaveCount(0);
    // Listed encounters are all public, so the card no longer says so.
    await expect(card.getByText("Public", { exact: true })).toHaveCount(0);
  });

  test("an upcoming encounter with every seat taken says it is full", async ({ page }) => {
    await page.goto(FEED);

    const card = page.locator("#events").getByRole("link").filter({ hasText: "Sold Out Duel" });
    await expect(card.getByText("Full", { exact: true })).toBeVisible();
    await expect(card.getByText(/spots? left/)).toHaveCount(0);
  });

  test("a single past item stays a card, not an archive row", async ({ page }) => {
    await page.goto(FEED);

    await expect(page.getByRole("heading", { name: "Past" })).toBeVisible();
    await expect(calendarPage(page, "Old Tuesday Table")).toBeVisible();
    await expect(page.getByText(/^Show older/)).toHaveCount(0);
  });
});
