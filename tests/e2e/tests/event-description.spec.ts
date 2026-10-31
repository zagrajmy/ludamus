import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";

// NOTE: seeded by _seed_feed_cards_sphere in scripts/bootstrap_data.py.
const FEED = "http://feed.localhost:8000/";
const EVENT = "Harvest Convention";

test.describe("Event description Markdown", () => {
  test("renders on the event page and reads as plain text on its card and link preview", async ({
    page,
  }) => {
    await page.goto(FEED);
    const card = page.locator("#events").getByRole("link").filter({ hasText: EVENT });
    await expect(card).toContainText("Three days of board games and open tables.");
    await expect(card).not.toContainText("**");
    await expect(card).not.toContainText("](");

    await card.click();
    await expect(page.getByRole("heading", { name: EVENT, level: 1 })).toBeVisible();
    const description = page.locator(".prose").filter({ hasText: "Three days of" });
    await expect(description.locator("strong")).toHaveText("board games");
    await expect(description.getByRole("link", { name: "open tables" })).toHaveAttribute(
      "href",
      "https://example.com/tables",
    );
    await expect(description.locator("p")).toHaveText([
      "Three days of board games and open tables.",
      "The bar stays open late.",
    ]);
    const summary = "Three days of board games and open tables. The bar stays open late.";
    for (const meta of [
      'meta[name="description"]',
      'meta[property="og:description"]',
      'meta[name="twitter:description"]',
    ]) {
      await expect(page.locator(meta)).toHaveAttribute("content", summary);
    }
    await attachArtifacts(test.info(), {
      name: "event-description",
      region: description,
      facts: { source: page.url() },
    });
  });
});
