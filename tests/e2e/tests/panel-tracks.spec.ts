import { type Page } from "@playwright/test";

import { attachArtifacts } from "./helpers/artifacts";
import { signInAsManager } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

// NOTE: "Thornwood Tabletop Days" (bootstrap_data.py) is seeded for this spec
// alone: a lodge with three rooms and no tracks. A track a failed or killed run
// left behind is deleted on the way in and on the way out.
const TRACKS_URL = "/panel/event/thornwood-days/tracks/";
const TRACK = "Lantern Stories";

const deleteLeftoverTrack = async (page: Page): Promise<void> => {
  await page.goto(TRACKS_URL);
  const leftover = page.getByRole("row", { name: new RegExp(TRACK) });
  if ((await leftover.count()) === 0) return;
  await leftover.getByRole("button", { name: "Delete" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Confirm" }).click();
  await expect(leftover).toHaveCount(0);
};

test.describe("Panel track setup", () => {
  test.beforeEach(async ({ page }) => {
    await signInAsManager(page);
    await deleteLeftoverTrack(page);
  });

  test.afterEach(async ({ page }) => {
    await deleteLeftoverTrack(page);
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

    await test.step("the edit form comes back with what was saved already ticked", async () => {
      await row.getByRole("link", { name: "Edit" }).click();
      await expect(page.getByRole("heading", { name: "Edit Track" })).toBeVisible();
      await expect(page.getByRole("checkbox", { name: "Public track" })).not.toBeChecked();
      await expect(page.getByRole("checkbox", { name: "Oak Room" })).toBeChecked();
      await expect(page.getByRole("checkbox", { name: "Birch Room" })).toBeChecked();
      await expect(page.getByRole("checkbox", { name: "Cedar Room" })).not.toBeChecked();
      await expect(page.getByRole("checkbox", { name: "Local Manager" })).toBeChecked();
    });

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
      rooms: await row.getByRole("cell").nth(2).getByRole("listitem").allInnerTexts(),
      managers: await row.getByRole("cell").nth(3).getByRole("listitem").allInnerTexts(),
    };
    expect(facts).toEqual({
      track: TRACK,
      visibility: "Private",
      rooms: ["Birch Room", "Cedar Room"],
      managers: ["Local Manager"],
    });
    await attachArtifacts(testInfo, { name: "track-row", region: row, facts });

    await row.getByRole("button", { name: "Delete" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Confirm" }).click();
    await expect(page.getByText("Track deleted.")).toBeVisible();
    await expect(row).toHaveCount(0);
  });
});
