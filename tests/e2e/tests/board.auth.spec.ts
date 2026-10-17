import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";

test.describe("Board listings", () => {
  test("author publishes a listing, finds it on the board, and closes it", async ({ page }) => {
    const title = `Mörk Borg one-shot ${Date.now()}`;

    await page.goto("/board/create/");
    await page.getByLabel("A GM").first().check();
    await page.getByLabel("Players").check();
    await page.getByLabel("Title").fill(title);
    await page.getByLabel("What we'll do").fill("A grim dungeon crawl");
    await page.getByLabel("When, in your words").fill("Every other Friday evening");
    await page.getByLabel("Online or offline").fill("Online on Discord");
    await attachArtifacts(test.info(), {
      name: "listing-form",
      region: page.getByRole("main"),
      facts: { title },
    });
    await page.getByRole("button", { name: "Publish listing" }).click();

    await expect(page.getByRole("heading", { name: title })).toBeVisible();
    await expect(page.getByText("Listing published.")).toBeVisible();
    await attachArtifacts(test.info(), {
      name: "listing-detail",
      region: page.getByRole("main"),
      facts: { title, status: "open" },
    });

    await page.goto("/board/");
    const card = page.getByRole("link", { name: new RegExp(title) });
    await expect(card).toContainText("GM looking for players");
    await expect(card).toContainText("Every other Friday evening");
    await attachArtifacts(test.info(), {
      name: "board-listing",
      region: page.getByRole("main"),
      facts: { title, pair: "GM looking for players", when: "Every other Friday evening" },
    });

    await card.click();
    await page.getByRole("button", { name: "Close listing" }).click();
    await expect(page.getByText("Listing closed.")).toBeVisible();
    await expect(page.getByText("Ended")).toBeVisible();

    await page.goto("/board/");
    await expect(page.getByRole("link", { name: new RegExp(title) })).toHaveCount(0);
  });

  test("asks for a date or a description of when", async ({ page }) => {
    await page.goto("/board/create/");
    await page.getByLabel("A GM").first().check();
    await page.getByLabel("Players").check();
    await page.getByLabel("Title").fill("No time given");
    await page.getByLabel("What we'll do").fill("Board games");
    await page.getByRole("button", { name: "Publish listing" }).click();

    await expect(page.getByText("Give a date and time, or describe when.")).toBeVisible();
    await expect(page.getByLabel("Title")).toHaveValue("No time given");
  });
});
