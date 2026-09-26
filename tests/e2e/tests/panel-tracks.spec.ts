import { writeFile } from "node:fs/promises";

import { expect, test } from "./helpers/fixtures";

// "Thornwood Tabletop Days" (bootstrap_data.py) is seeded for this spec alone:
// a lodge with three rooms and no tracks. The walkthrough deletes the track it
// creates, so a second run against the same database starts from the same
// empty list.
const TRACKS_URL = "/panel/event/thornwood-days/tracks/";
const TRACK = "Lantern Stories";

test.describe("Panel track setup", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Username:").fill("e2e-manager");
    await page.getByLabel("Password:").fill("e2e-manager-123");
    await page.getByRole("button", { name: /Log in/i }).click();
  });

  test.afterEach(async ({ page }) => {
    await page.goto(TRACKS_URL);
    const leftover = page.getByRole("row", { name: new RegExp(TRACK) });
    if ((await leftover.count()) === 0) return;
    await leftover.getByRole("button", { name: "Delete" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Confirm" }).click();
    await expect(leftover).toHaveCount(0);
  });

  test("organizer sets up a private track with rooms and a manager, then moves its rooms", async ({
    page,
  }, testInfo) => {
    await page.goto(TRACKS_URL);
    await page.getByRole("link", { name: "New Track" }).first().click();

    await page.getByLabel("Name").fill(TRACK);
    await page.getByRole("checkbox", { name: "Public track" }).uncheck();
    await page.getByRole("checkbox", { name: "Oak Room" }).check();
    await page.getByRole("checkbox", { name: "Birch Room" }).check();
    await page.getByRole("checkbox", { name: "Local Manager" }).check();
    await page.getByRole("button", { name: "Create Track" }).click();

    await page.waitForURL(/\/tracks\/$/);
    await expect(page.getByText("Track created successfully.")).toBeVisible();
    const row = page.getByRole("row", { name: new RegExp(TRACK) });
    await expect(row.getByText("Private", { exact: true })).toBeVisible();
    await expect(row.getByText("Oak Room")).toBeVisible();
    await expect(row.getByText("Birch Room")).toBeVisible();
    await expect(row.getByText("Cedar Room")).toHaveCount(0);
    await expect(row.getByText("Local Manager")).toBeVisible();

    // The edit form comes back with what was saved already ticked.
    await row.getByRole("link", { name: "Edit" }).click();
    await expect(page.getByRole("heading", { name: "Edit Track" })).toBeVisible();
    await expect(page.getByRole("checkbox", { name: "Public track" })).not.toBeChecked();
    await expect(page.getByRole("checkbox", { name: "Oak Room" })).toBeChecked();
    await expect(page.getByRole("checkbox", { name: "Birch Room" })).toBeChecked();
    await expect(page.getByRole("checkbox", { name: "Cedar Room" })).not.toBeChecked();
    await expect(page.getByRole("checkbox", { name: "Local Manager" })).toBeChecked();

    await page.getByRole("checkbox", { name: "Oak Room" }).uncheck();
    await page.getByRole("checkbox", { name: "Cedar Room" }).check();
    await page.getByRole("button", { name: "Save Changes" }).click();

    await page.waitForURL(/\/tracks\/$/);
    await expect(page.getByText("Track updated successfully.")).toBeVisible();
    await page.reload();
    await expect(row.getByText("Birch Room")).toBeVisible();
    await expect(row.getByText("Cedar Room")).toBeVisible();
    await expect(row.getByText("Oak Room")).toHaveCount(0);
    await expect(row.getByText("Private", { exact: true })).toBeVisible();
    await expect(row.getByText("Local Manager")).toBeVisible();

    const facts = {
      track: TRACK,
      visibility: (await row.getByRole("cell").nth(1).innerText()).trim(),
      rooms: await row.getByRole("cell").nth(2).locator("[title]").allInnerTexts(),
      managers: await row.getByRole("cell").nth(3).locator("[title]").allInnerTexts(),
    };
    expect(facts).toEqual({
      track: TRACK,
      visibility: "Private",
      rooms: ["Birch Room", "Cedar Room"],
      managers: ["Local Manager"],
    });
    const screenshotPath = testInfo.outputPath("track-row.png");
    await row.screenshot({ path: screenshotPath });
    await testInfo.attach("track-row.png", { path: screenshotPath, contentType: "image/png" });
    const factsPath = testInfo.outputPath("track-row.json");
    await writeFile(factsPath, `${JSON.stringify(facts, null, 2)}\n`);
    await testInfo.attach("track-row.json", { path: factsPath, contentType: "application/json" });

    await row.getByRole("button", { name: "Delete" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Confirm" }).click();
    await expect(page.getByText("Track deleted.")).toBeVisible();
    await expect(row).toHaveCount(0);
  });
});
