import { type Page } from "@playwright/test";
import { writeFile } from "node:fs/promises";

import { expect, test } from "./helpers/fixtures";

// NOTE: "Lowtide Fair" (bootstrap_timetable.py) has one room, the Heron Room, with
// Salt Road and Tide Reckoning both booked into it at 10:00. The walkthrough
// takes Tide Reckoning off the grid and assigns it back to the top of the
// room's column, 10:00 again, so it leaves the event as it found it.
const TIMETABLE_URL = "/panel/event/lowtide-fair/timetable/";
const MOVED = "Tide Reckoning";

const heading = (page: Page) => page.locator("#conflicts-fold > summary");
const panel = (page: Page) => page.locator("#conflict-panel");
const grid = (page: Page) => page.locator("#timetable-grid");
const sessionsToAssign = (page: Page) => page.getByRole("region", { name: "Sessions to assign" });

const conflictCount = async (page: Page): Promise<number> => {
  const match = /(\d+) conflicts?/.exec(await panel(page).innerText());
  if (!match) throw new Error("The conflict panel shows no count");
  return Number(match[1]);
};

const countWording = (count: number) => new RegExp(`^\\s*⚠\\s*${count} conflicts?\\s*$`);

test.describe("Timetable conflict count", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Username:").fill("e2e-manager");
    await page.getByLabel("Password:").fill("e2e-manager-123");
    await page.getByRole("button", { name: /Log in/i }).click();
  });

  test("the conflicts heading follows the schedule as sessions come off and back on", async ({
    page,
  }, testInfo) => {
    await page.goto(TIMETABLE_URL);
    const clashing = await conflictCount(page);
    expect(clashing).toBeGreaterThan(0);
    await expect(heading(page)).toHaveText(countWording(clashing));

    const leftPane = page.locator("#left-pane");
    await grid(page).getByText(MOVED).click();
    await leftPane.getByRole("button", { name: "Unassign" }).click();
    await expect(sessionsToAssign(page).getByText(MOVED)).toBeVisible();
    await expect(panel(page)).toHaveText(/^\s*✓\s*All clear\s*$/);
    await expect(heading(page)).toHaveText(/^\s*✓\s*All clear\s*$/);
    const cleared = {
      heading: (await heading(page).innerText()).replace(/\s+/g, " ").trim(),
      panel: (await panel(page).innerText()).replace(/\s+/g, " ").trim(),
    };

    await sessionsToAssign(page).locator("[data-session-pk]", { hasText: MOVED }).click();
    await leftPane.getByRole("button", { name: "Assign" }).click();
    await page
      .locator(".timetable-column.assign-mode-active")
      .first()
      .click({ position: { x: 50, y: 1 } });
    await expect(grid(page).getByText(MOVED)).toBeVisible();
    await expect(heading(page)).toHaveText(countWording(clashing));
    expect(await conflictCount(page)).toBe(clashing);

    const facts = {
      before: clashing,
      afterUnassign: cleared,
      afterReassign: {
        heading: (await heading(page).innerText()).replace(/\s+/g, " ").trim(),
        panel: await conflictCount(page),
      },
    };
    const screenshotPath = testInfo.outputPath("timetable-conflict-count.png");
    await page.getByRole("main").screenshot({ path: screenshotPath });
    await testInfo.attach("timetable-conflict-count.png", {
      path: screenshotPath,
      contentType: "image/png",
    });
    const factsPath = testInfo.outputPath("timetable-conflict-count.json");
    await writeFile(factsPath, `${JSON.stringify(facts, null, 2)}\n`);
    await testInfo.attach("timetable-conflict-count.json", {
      path: factsPath,
      contentType: "application/json",
    });
  });
});
