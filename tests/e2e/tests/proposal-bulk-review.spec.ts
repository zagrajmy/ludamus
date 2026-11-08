import { type Page } from "@playwright/test";

import { attachArtifacts } from "./helpers/artifacts";
import { managerState } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

// NOTE: quillmark-con holds three pending proposals and Anchored Saga, which is
// already on the agenda (bootstrap_data.py). The tests move statuses around
// and afterEach puts every pending one back, so a retry starts from the seed.
const LIST_URL = "/panel/event/quillmark-con/proposals/";
const PENDING = ["Ashen Choir", "Clockwork Duel", "Moonlit Heist"];

const flash = (page: Page, text: string) =>
  page.getByRole("region", { name: "Notifications" }).getByText(text);

const titles = (page: Page) =>
  page.getByRole("table").getByRole("rowgroup").nth(1).getByRole("row").getByRole("link");

const bulk = async (page: Page, action: string, picks: string[]) => {
  for (const title of picks) await page.getByRole("checkbox", { name: `Select ${title}` }).check();
  await expect(page.getByText(`Selected: ${picks.length}`)).toBeVisible();
  await page.getByRole("button", { name: action, exact: true }).click();
};

test.use({ storageState: managerState });
test.describe.configure({ mode: "serial" });

test.describe("Reviewing proposals in bulk", () => {
  test.afterEach(async ({ page }) => {
    await page.goto(`${LIST_URL}?status=all`);
    await bulk(page, "Move to pending", PENDING);
    await expect(flash(page, "3 proposals updated.")).toBeVisible();
  });

  test("accepting two at once sends both to the timetable and leaves the third to decide", async ({
    page,
  }, testInfo) => {
    await page.goto(LIST_URL);
    await expect(titles(page)).toHaveText(PENDING);

    await bulk(page, "Accept", ["Moonlit Heist", "Clockwork Duel"]);
    await expect(flash(page, "2 proposals updated.")).toBeVisible();
    await expect(titles(page)).toHaveText(["Ashen Choir"]);

    // Accepted and unplaced is exactly what the timetable asks the organizer to place.
    await page.goto("/panel/event/quillmark-con/timetable/");
    const toAssign = page.getByRole("region", { name: "Sessions to assign" });
    await expect(toAssign.getByText("Moonlit Heist")).toBeVisible();
    await expect(toAssign.getByText("Clockwork Duel")).toBeVisible();
    await expect(toAssign.getByText("Ashen Choir")).toHaveCount(0);
    await expect(toAssign.getByText("Anchored Saga")).toHaveCount(0);

    await attachArtifacts(testInfo, {
      name: "proposal-bulk-accept",
      region: toAssign,
      facts: { accepted: ["Clockwork Duel", "Moonlit Heist"], stillPending: ["Ashen Choir"] },
    });
  });

  test("a bulk reject skips the proposal already on the agenda and says why", async ({
    page,
  }, testInfo) => {
    await page.goto(`${LIST_URL}?status=all`);
    await bulk(page, "Reject", ["Ashen Choir", "Anchored Saga"]);
    await expect(flash(page, "1 proposal updated.")).toBeVisible();
    await expect(
      flash(
        page,
        "1 scheduled proposal was skipped; remove it from the timetable to change its status.",
      ),
    ).toBeVisible();

    await page.goto(`${LIST_URL}?status=rejected`);
    await expect(titles(page)).toHaveText(["Ashen Choir"]);

    // The skipped one is still where the public schedule shows it.
    await page.goto("/event/quillmark-con/");
    await expect(page.getByRole("link", { name: "Open details for Anchored Saga" })).toBeVisible();

    await page.goto(`${LIST_URL}?status=all`);
    const anchored = page.getByRole("row").filter({ hasText: "Anchored Saga" });
    await expect(anchored).toContainText("Scheduled");
    await attachArtifacts(testInfo, {
      name: "proposal-bulk-reject",
      region: page.getByRole("table"),
      facts: { rejected: ["Ashen Choir"], skippedAsScheduled: ["Anchored Saga"] },
    });
  });
});
