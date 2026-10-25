import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";

test.describe("Board listings", () => {
  test("author publishes a listing, finds it on the board, and closes it", async ({ page }) => {
    const title = `Mörk Borg one-shot ${Date.now()}`;

    await page.goto("/board/create/");
    await page.getByLabel("Players").check();
    await page.getByLabel("Title").fill(title);
    await page.getByLabel("What we'll do").fill("A grim dungeon crawl");
    await page.getByLabel("When, in your words").fill("Every other Friday evening");
    await page.getByLabel("Format").fill("Online on Discord");
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
    await expect(card).toContainText("Looking for players");
    await expect(card).toContainText("Every other Friday evening");
    await attachArtifacts(test.info(), {
      name: "board-listing",
      region: page.getByRole("main"),
      facts: { title, seeking: "Looking for players", when: "Every other Friday evening" },
    });

    await card.click();
    await page.getByRole("button", { name: "Close listing" }).click();
    await expect(page.getByText("Listing closed.")).toBeVisible();
    await expect(page.getByText("Ended")).toBeVisible();

    await page.getByRole("button", { name: "Reopen listing" }).click();
    await expect(page.getByText("Listing reopened.")).toBeVisible();
    await expect(page.getByText(/Open listings close 30 days after publishing/)).toBeVisible();
    await page.getByRole("button", { name: "Close listing" }).click();

    await page.getByRole("main").getByRole("link", { name: "Board", exact: true }).click();
    await expect(page).toHaveURL(/\/board\/$/);
    await expect(page.getByRole("link", { name: new RegExp(title) })).toHaveCount(0);
  });

  test("asks for a date or a description of when", async ({ page }) => {
    await page.goto("/board/create/");
    const when = page.getByRole("group", { name: "When" });
    await expect(when).toHaveAccessibleDescription(/Required, drafts too/);
    await page.getByLabel("Players").check();
    await page.getByLabel("Title").fill("No time given");
    await page.getByLabel("What we'll do").fill("Board games");
    await page.getByRole("button", { name: "Publish listing" }).click();

    await expect(page.getByText("Give a date and time, or describe when.")).toBeVisible();
    await expect(page.getByLabel("Title")).toHaveValue("No time given");
  });
});

test.describe("Board listings, edge cases", () => {
  test("long unbroken text stays inside a phone-width page", async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const unbroken = "x".repeat(120);
    const title = `T${Date.now()}${unbroken}`;

    await page.goto("/board/create/");
    await page.getByLabel("Players").check();
    await page.getByLabel("Title").fill(title);
    await page.getByLabel("What we'll do").fill(unbroken);
    await page.getByLabel("When, in your words").fill(unbroken);
    await page.getByLabel("Format").fill(unbroken);
    await page.getByLabel("Where").fill(unbroken);
    await page.getByRole("button", { name: "Publish listing" }).click();
    await expect(page.getByText("Listing published.")).toBeVisible();

    const widths = async () =>
      page.evaluate(() => ({
        scroll: document.documentElement.scrollWidth,
        client: document.documentElement.clientWidth,
      }));
    const detail = await widths();
    expect(detail.scroll).toBeLessThanOrEqual(detail.client);

    await page.goto("/board/");
    const board = await widths();
    expect(board.scroll).toBeLessThanOrEqual(board.client);
    await attachArtifacts(testInfo, {
      name: "board-long-text-mobile",
      region: page.getByRole("main"),
      facts: { detail, board },
    });
  });

  test("cancel leaves the form for the board without saving", async ({ page }) => {
    const title = `Cancelled ${Date.now()}`;
    await page.goto("/board/create/");
    await page.getByLabel("Title").fill(title);
    await page.getByRole("link", { name: "Cancel" }).click();

    await expect(page).toHaveURL(/\/board\/$/);
    await expect(page.getByRole("link", { name: new RegExp(title) })).toHaveCount(0);
  });
});
