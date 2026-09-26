import { type Browser, type Locator, type Page } from "@playwright/test";

import { attachArtifacts } from "./helpers/artifacts";
import { signInAsManager } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

// NOTE: "Emberfall Convention" (bootstrap_timetable.py) is seeded for this spec
// alone, with one of every scheduling problem:
//   Amber Room   (6)  Story Games  Clockwork Heist 10:00-11:00, Ghost Ship Salvage 10:30-11:30
//   Cobalt Room  (8)  Story Games  Tidepool Tales 10:00-11:00 (Rowan Hale),
//                                  Moonlit Duel 14:00-15:00, asked for the 10:00-12:00 slot
//   Basalt Room (10)  Miniatures   Lantern Market 10:00-11:00 (Rowan Hale),
//                                  Giant Mech Brawl 14:00-15:00 for 20 people
// Story Games is managed by Local Manager. The second test unschedules Ghost
// Ship Salvage and reverts it, so the two run in order, and the group puts the
// session back before and after in case an attempt died in between.
test.describe.configure({ mode: "serial" });

const TIMETABLE_URL = "/panel/event/emberfall-con/timetable/";
const GHOST_SHIP = "Ghost Ship Salvage";

// NOTE: a clash is listed once, from whichever of its two sessions the event lists
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

const conflicts = (page: Page) => page.getByRole("region", { name: "Conflicts", exact: true });

const conflictGroup = (page: Page, label: string) =>
  conflicts(page).getByRole("region", { name: new RegExp(`^${label}\\b`) });

const schedule = (page: Page) => page.getByRole("region", { name: "Schedule" });

const sessionsToAssign = (page: Page) => page.getByRole("region", { name: "Sessions to assign" });

const revertLatestRemoval = async (page: Page): Promise<void> => {
  await page.getByRole("tab", { name: "Activity Log" }).click();
  const removal = page
    .getByRole("row", { name: new RegExp(GHOST_SHIP) })
    .filter({ hasText: "Removed" })
    .first();
  await removal.getByRole("button", { name: "Revert" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Revert" }).click();
  await expect(removal.getByRole("button", { name: "Revert" })).toHaveCount(0);
};

const restoreSeededSchedule = async (page: Page): Promise<void> => {
  await page.goto(TIMETABLE_URL);
  await expect(schedule(page).getByRole("button", { name: /Clockwork Heist/ })).toBeVisible();
  await expect(sessionsToAssign(page).getByText("Loading…")).toHaveCount(0);
  if ((await sessionsToAssign(page).getByText(GHOST_SHIP).count()) === 0) return;
  await revertLatestRemoval(page);
  await page.goto(TIMETABLE_URL);
  await expect(schedule(page).getByRole("button", { name: new RegExp(GHOST_SHIP) })).toBeVisible();
};

const withManager = async (browser: Browser, act: (page: Page) => Promise<void>): Promise<void> => {
  const page = await browser.newPage();
  await signInAsManager(page);
  await act(page);
  await page.close();
};

const squash = (text: string) => text.replace(/\s+/g, " ").trim();

async function groupFacts(page: Page, label: string) {
  const group = conflictGroup(page, label);
  const heading = squash(await group.getByRole("heading").innerText());
  return {
    count: Number(/\d+$/.exec(heading)?.[0]),
    entries: (await group.getByRole("listitem").allInnerTexts()).map(squash),
  };
}

const ROOMS = ["Amber Room", "Basalt Room", "Cobalt Room"];
const SESSIONS = [
  "Clockwork Heist",
  GHOST_SHIP,
  "Tidepool Tales",
  "Moonlit Duel",
  "Lantern Market",
  "Giant Mech Brawl",
];

const shownOf = async (names: string[], locate: (name: string) => Locator) => {
  const shown = [];
  for (const name of names) {
    if ((await locate(name).count()) > 0) shown.push(name);
  }
  return shown;
};

const countOf = (label: string, count: number) => new RegExp(`${label}\\s+${count}\\b`);

test.describe("Timetable problems", () => {
  test.beforeAll(async ({ browser }) => {
    await withManager(browser, restoreSeededSchedule);
  });

  test.afterAll(async ({ browser }) => {
    await withManager(browser, restoreSeededSchedule);
  });

  test.beforeEach(async ({ page }) => {
    await signInAsManager(page);
  });

  test("organizer reviews every kind of scheduling problem", async ({ page }, testInfo) => {
    await page.goto(TIMETABLE_URL);
    await expect(conflicts(page)).toContainText("3 conflicts");

    await page.getByRole("tab", { name: "Problems" }).click();
    await expect(page).toHaveURL(/\/timetable\/problems\/$/);

    for (const [label, wording] of Object.entries(PROBLEMS)) {
      const group = conflictGroup(page, label);
      await expect(group).toContainText(countOf(label, 1));
      await expect(group).toContainText(wording);
    }

    const outsideSlots = page.getByRole("region", { name: "Sessions outside preferred slots" });
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
      region: page.getByRole("main"),
      facts: {
        conflicts: {
          "Room overlaps": await groupFacts(page, "Room overlaps"),
          "Facilitator overlaps": await groupFacts(page, "Facilitator overlaps"),
          "Capacity exceeded": await groupFacts(page, "Capacity exceeded"),
        },
        outsidePreferredSlots: (
          await outsideSlots.getByRole("heading", { level: 3 }).allInnerTexts()
        ).map(squash),
      },
    });
  });

  test("organizer narrows the timetable to a track, clears its room clash and undoes it", async ({
    page,
  }, testInfo) => {
    await page.goto(TIMETABLE_URL);
    await page.getByLabel("Track:").selectOption({ label: "Story Games" });
    await expect(page).toHaveURL(/[?&]track=\d+/);

    await test.step("only this track's rooms, and the sessions booked in them, stay on the grid", async () => {
      await expect(schedule(page).getByText("Amber Room")).toBeVisible();
      await expect(schedule(page).getByText("Cobalt Room")).toBeVisible();
      await expect(schedule(page).getByText("Basalt Room")).toHaveCount(0);
      for (const title of ["Clockwork Heist", GHOST_SHIP, "Tidepool Tales", "Moonlit Duel"]) {
        await expect(schedule(page).getByRole("button", { name: new RegExp(title) })).toBeVisible();
      }
      for (const title of ["Lantern Market", "Giant Mech Brawl"]) {
        await expect(schedule(page).getByRole("button", { name: new RegExp(title) })).toHaveCount(
          0,
        );
      }
    });

    const panel = conflicts(page);
    await test.step("the track's clashes include one another track's session causes, not that track's over-capacity session", async () => {
      await expect(panel).toContainText("2 conflicts");
      await expect(panel).toContainText(/Room occupied by: (Ghost Ship Salvage|Clockwork Heist)/);
      await expect(panel).toContainText("Rowan Hale facilitates simultaneously: Lantern Market");
      await expect(panel).toContainText("Track: Miniatures");
      await expect(panel).not.toContainText("Room fits");
    });

    await test.step("taking a clashing session off the grid refreshes the track's conflicts", async () => {
      await schedule(page)
        .getByRole("button", { name: new RegExp(GHOST_SHIP) })
        .click();
      await page.getByRole("button", { name: "Unassign" }).click();
      await expect(sessionsToAssign(page).getByText(GHOST_SHIP)).toBeVisible();
      await expect(panel).toContainText("1 conflict");
      await expect(panel).not.toContainText("Room occupied by");
      await expect(panel).toContainText("Rowan Hale facilitates simultaneously: Lantern Market");
    });

    await attachArtifacts(testInfo, {
      name: "story-games-timetable",
      region: page.getByRole("main"),
      facts: {
        track: "Story Games",
        rooms: await shownOf(ROOMS, (room) => schedule(page).getByText(room, { exact: true })),
        scheduled: await shownOf(SESSIONS, (title) =>
          schedule(page).getByRole("button", { name: new RegExp(title) }),
        ),
        conflictsAfterUnassign: squash(await panel.innerText()),
      },
    });

    await page.getByRole("tab", { name: "Problems" }).click();
    await expect(conflictGroup(page, "Room overlaps")).toHaveCount(0);
    await expect(conflictGroup(page, "Facilitator overlaps")).toBeVisible();
    await expect(conflictGroup(page, "Capacity exceeded")).toBeVisible();

    await test.step("reverting the removal from the activity log puts the session back", async () => {
      await revertLatestRemoval(page);
    });

    await page.getByRole("tab", { name: "Problems" }).click();
    await page.reload();
    const roomOverlaps = conflictGroup(page, "Room overlaps");
    await expect(roomOverlaps).toContainText(countOf("Room overlaps", 1));
    await expect(roomOverlaps).toContainText(ROOM_CLASH);
  });
});
