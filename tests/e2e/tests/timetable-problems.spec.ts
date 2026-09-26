import { type Locator, type Page, type TestInfo } from "@playwright/test";
import { writeFile } from "node:fs/promises";

import { expect, test } from "./helpers/fixtures";

// "Emberfall Convention" (bootstrap_timetable.py) is seeded for this spec alone,
// with one of every scheduling problem:
//   Amber Room   (6)  Story Games  Clockwork Heist 10:00-11:00, Ghost Ship Salvage 10:30-11:30
//   Cobalt Room  (8)  Story Games  Tidepool Tales 10:00-11:00 (Rowan Hale),
//                                  Moonlit Duel 14:00-15:00, asked for the 10:00-12:00 slot
//   Basalt Room (10)  Miniatures   Lantern Market 10:00-11:00 (Rowan Hale),
//                                  Giant Mech Brawl 14:00-15:00 for 20 people
// Story Games is managed by Local Manager. The second test unschedules a
// session and reverts it from the activity log, so the two run in order and
// leave the event as they found it.
test.describe.configure({ mode: "serial" });

const TIMETABLE_URL = "/panel/event/emberfall-con/timetable/";

// A clash is listed once, from whichever of its two sessions the event lists
// first, so either wording is the right one. Regexes match the raw text, so
// spaces stand for any run of the template's whitespace.
const either = (...wordings: string[]) =>
  new RegExp(
    wordings
      .map((text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/ /g, "\\s+"))
      .join("|"),
  );
const ROOM_CLASH = either(
  "Clockwork Heist — Room occupied by: Ghost Ship Salvage",
  "Ghost Ship Salvage — Room occupied by: Clockwork Heist",
);
const PROBLEMS = {
  "Room overlaps": ROOM_CLASH,
  "Facilitator overlaps": either(
    "Tidepool Tales — Rowan Hale facilitates simultaneously: Lantern Market (track: Miniatures)",
    "Lantern Market — Rowan Hale facilitates simultaneously: Tidepool Tales (track: Story Games)",
  ),
  "Capacity exceeded": either("Giant Mech Brawl — Room fits 10 people, session requires 20"),
};

const conflictsSection = (page: Page) =>
  page.locator("section").filter({ has: page.getByRole("heading", { name: "Conflicts" }) });

const conflictGroup = (page: Page, label: string) =>
  conflictsSection(page).locator(":scope > div").filter({ hasText: label });

const conflictsSummary = (page: Page) => page.locator("#conflicts-fold > summary");

const schedule = (page: Page) => page.getByRole("region", { name: "Schedule" });

async function attachArtifacts(
  testInfo: TestInfo,
  { name, region, facts }: { name: string; region: Locator; facts: object },
) {
  const screenshotPath = testInfo.outputPath(`${name}.png`);
  await region.screenshot({ path: screenshotPath });
  await testInfo.attach(`${name}.png`, { path: screenshotPath, contentType: "image/png" });
  const factsPath = testInfo.outputPath(`${name}.json`);
  await writeFile(factsPath, `${JSON.stringify(facts, null, 2)}\n`);
  await testInfo.attach(`${name}.json`, { path: factsPath, contentType: "application/json" });
}

// A group reads as its label, its count, then one line per clash.
async function groupFacts(page: Page, label: string) {
  const lines = (await conflictGroup(page, label).innerText())
    .split("\n")
    .map((line) => line.replace(/\s+/g, " ").trim())
    .filter(Boolean);
  return { count: Number(lines[1]), entries: lines.slice(2) };
}

const countOf = (label: string, count: number) => new RegExp(`${label}\\s+${count}\\b`);

test.describe("Timetable problems", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Username:").fill("e2e-manager");
    await page.getByLabel("Password:").fill("e2e-manager-123");
    await page.getByRole("button", { name: /Log in/i }).click();
  });

  test("organizer reviews every kind of scheduling problem", async ({ page }, testInfo) => {
    await page.goto(TIMETABLE_URL);
    await expect(conflictsSummary(page)).toHaveText(/3 conflicts/);

    await page.getByRole("tab", { name: "Problems" }).click();
    await expect(page).toHaveURL(/\/timetable\/problems\/$/);

    for (const [label, wording] of Object.entries(PROBLEMS)) {
      const group = conflictGroup(page, label);
      await expect(group).toContainText(countOf(label, 1));
      await expect(group).toContainText(wording);
    }

    const outsideSlots = page
      .locator("section")
      .filter({ has: page.getByRole("heading", { name: "Sessions outside preferred slots" }) });
    await expect(outsideSlots).toContainText("Moonlit Duel");
    await expect(outsideSlots).toContainText(/Scheduled: .* 14:00 – 15:00/);
    await expect(outsideSlots.getByRole("listitem")).toHaveText([/10:00 – 12:00/]);
    await expect(outsideSlots).toContainText("Track: Story Games (managed by: Local Manager)");
    await expect(outsideSlots).not.toContainText("Giant Mech Brawl");

    await outsideSlots.getByRole("link", { name: "Open in Schedule" }).click();
    await expect(page).toHaveURL(/\/timetable\/$/);
    await expect(schedule(page).getByRole("button", { name: /Moonlit Duel/ })).toContainText("⏰");

    await page.goBack();
    await attachArtifacts(testInfo, {
      name: "problems",
      region: page.locator("main"),
      facts: {
        conflicts: {
          "Room overlaps": await groupFacts(page, "Room overlaps"),
          "Facilitator overlaps": await groupFacts(page, "Facilitator overlaps"),
          "Capacity exceeded": await groupFacts(page, "Capacity exceeded"),
        },
        outsidePreferredSlots: (await outsideSlots.locator(".font-medium").allInnerTexts()).map(
          (text) => text.trim(),
        ),
      },
    });
  });

  test("organizer narrows the timetable to a track, clears its room clash and undoes it", async ({
    page,
  }, testInfo) => {
    await page.goto(TIMETABLE_URL);
    await page.getByLabel("Track:").selectOption({ label: "Story Games" });
    await expect(page).toHaveURL(/[?&]track=\d+/);

    // Only this track's rooms, and the sessions booked in them, stay on the grid.
    await expect(schedule(page).getByText("Amber Room")).toBeVisible();
    await expect(schedule(page).getByText("Cobalt Room")).toBeVisible();
    await expect(schedule(page).getByText("Basalt Room")).toHaveCount(0);
    for (const title of [
      "Clockwork Heist",
      "Ghost Ship Salvage",
      "Tidepool Tales",
      "Moonlit Duel",
    ]) {
      await expect(schedule(page).getByRole("button", { name: new RegExp(title) })).toBeVisible();
    }
    for (const title of ["Lantern Market", "Giant Mech Brawl"]) {
      await expect(schedule(page).getByRole("button", { name: new RegExp(title) })).toHaveCount(0);
    }

    // The track's own clashes, including the one another track's session
    // causes; the other track's over-capacity session is not this track's.
    await expect(conflictsSummary(page)).toHaveText(/2 conflicts/);
    const panel = page.locator("#conflict-panel");
    await expect(panel).toContainText(/Room occupied by: (Ghost Ship Salvage|Clockwork Heist)/);
    await expect(panel).toContainText("Rowan Hale facilitates simultaneously: Lantern Market");
    await expect(panel).toContainText("Track: Miniatures");
    await expect(panel).not.toContainText("Room fits");

    // Take one of the clashing sessions off the grid: the track's conflict
    // list refreshes to what is left.
    await schedule(page)
      .getByRole("button", { name: /Ghost Ship Salvage/ })
      .click();
    const leftPane = page.locator("#left-pane");
    await leftPane.getByRole("button", { name: "Unassign" }).click();
    await expect(
      page.getByRole("region", { name: "Sessions to assign" }).getByText("Ghost Ship Salvage"),
    ).toBeVisible();
    await expect(panel).toContainText("1 conflict");
    await expect(panel).not.toContainText("Room occupied by");
    await expect(panel).toContainText("Rowan Hale facilitates simultaneously: Lantern Market");

    await attachArtifacts(testInfo, {
      name: "story-games-timetable",
      region: page.locator("main"),
      facts: {
        track: "Story Games",
        rooms: await schedule(page)
          .locator(".timetable-room-cell > div:first-child")
          .allInnerTexts(),
        scheduled: (await schedule(page).locator(".timetable-session").allInnerTexts()).map(
          (text) => text.split("\n")[0]?.replace(/^[⚠⏰]\s*/u, ""),
        ),
        conflictsAfterUnassign: (await panel.innerText()).replace(/\s+/g, " ").trim(),
      },
    });

    await page.getByRole("tab", { name: "Problems" }).click();
    await expect(conflictGroup(page, "Room overlaps")).toHaveCount(0);
    await expect(conflictGroup(page, "Facilitator overlaps")).toBeVisible();
    await expect(conflictGroup(page, "Capacity exceeded")).toBeVisible();

    // Undo from the activity log puts the session back where it was.
    await page.getByRole("tab", { name: "Activity Log" }).click();
    const removal = page
      .getByRole("row", { name: /Ghost Ship Salvage/ })
      .filter({ hasText: "Removed" })
      .first();
    await removal.getByRole("button", { name: "Revert" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Revert" }).click();
    // Reverted, the removal is no longer the latest change, so it cannot be
    // reverted again.
    await expect(removal.getByRole("button", { name: "Revert" })).toHaveCount(0);

    await page.getByRole("tab", { name: "Problems" }).click();
    await page.reload();
    const roomOverlaps = conflictGroup(page, "Room overlaps");
    await expect(roomOverlaps).toContainText(countOf("Room overlaps", 1));
    await expect(roomOverlaps).toContainText(ROOM_CLASH);
  });
});
