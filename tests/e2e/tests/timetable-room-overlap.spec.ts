import { type Page } from "@playwright/test";

import { attachArtifacts } from "./helpers/artifacts";
import { managerState } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

// NOTE: "Shared Hearth" (bootstrap_timetable.py) has one room. Morning Hearth
// is at 10:00 and Later Hearth at 12:00. This spec moves Later Hearth onto
// Morning Hearth, then moves Morning Hearth to 12:00, and leaves them apart.
const TIMETABLE_URL = "/panel/event/shared-hearth/timetable/";
const PUBLIC_URL = "/event/shared-hearth/";
const ROOM = "Hearth Room";
const MORNING = "Morning Hearth";
const LATER = "Later Hearth";

const fold = (page: Page) => page.locator("#conflicts-fold");
const summary = (page: Page) => fold(page).locator("summary");
const conflicts = (page: Page) => page.locator("#conflict-panel");
const room = (page: Page) => page.getByRole("group", { name: ROOM });

const openConflicts = async (page: Page): Promise<void> => {
  if ((await fold(page).getAttribute("open")) === null) await summary(page).click();
};

const dragBy = async (page: Page, title: string, minutes: number): Promise<void> => {
  const block = room(page).getByRole("button", { name: title });
  await expect(block).toBeVisible();
  const box = (await block.boundingBox())!;
  const minutePx = box.height / 60;
  const grab = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
  await page.mouse.move(grab.x, grab.y);
  await page.mouse.down();
  await page.mouse.move(grab.x, grab.y + minutes * minutePx, { steps: 12 });
};

test.describe("Room overlap on the timetable", () => {
  test.use({ storageState: managerState });

  test("moving onto another session in the room warns, places, and clears again", async ({
    page,
  }, testInfo) => {
    await page.goto(TIMETABLE_URL);
    await expect(room(page).getByRole("button", { name: MORNING })).toBeVisible();
    await expect(room(page).getByRole("button", { name: LATER })).toBeVisible();
    await expect(summary(page)).toContainText("All clear");

    await dragBy(page, LATER, -120);
    await expect(page.getByText("Room taken")).toBeVisible();
    const onto = page.waitForResponse(
      (response) => response.url().includes("/do/assign/") && response.request().method() === "POST",
    );
    await page.mouse.up();
    expect((await onto).status()).toBe(204);

    await expect(room(page).getByRole("button", { name: MORNING })).toBeVisible();
    await expect(room(page).getByRole("button", { name: LATER })).toBeVisible();
    await expect(summary(page)).toContainText("1 conflict");
    await openConflicts(page);
    await expect(conflicts(page)).toContainText("Room occupied by");
    await expect(conflicts(page)).toContainText(MORNING);
    await expect(conflicts(page)).toContainText(LATER);
    await attachArtifacts(testInfo, {
      name: "room-overlap-warning",
      region: page.getByRole("main"),
      facts: { room: ROOM, overlapping: [MORNING, LATER], warning: "Room occupied by" },
    });

    await page.goto(PUBLIC_URL);
    await expect(page.getByRole("heading", { name: MORNING })).toBeVisible();
    await expect(page.getByRole("heading", { name: LATER })).toBeVisible();
    await attachArtifacts(testInfo, {
      name: "room-overlap-public-schedule",
      region: page.getByRole("main"),
      facts: { url: PUBLIC_URL, visible: [MORNING, LATER] },
    });

    await page.goto(TIMETABLE_URL);
    await dragBy(page, MORNING, 120);
    const away = page.waitForResponse(
      (response) => response.url().includes("/do/assign/") && response.request().method() === "POST",
    );
    await page.mouse.up();
    expect((await away).status()).toBe(204);

    await expect(room(page).getByRole("button", { name: MORNING })).toBeVisible();
    await expect(room(page).getByRole("button", { name: LATER })).toBeVisible();
    await expect(summary(page)).toContainText("All clear");
    await expect(conflicts(page)).not.toContainText("Room occupied by");
    await attachArtifacts(testInfo, {
      name: "room-overlap-cleared",
      region: page.getByRole("main"),
      facts: { room: ROOM, warning: "All clear" },
    });
  });
});
