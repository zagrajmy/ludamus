import { type Page } from "@playwright/test";

import { attachArtifacts } from "./helpers/artifacts";
import { managerState } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

// NOTE: "Shared Hearth" (bootstrap_timetable.py) books Morning Hearth at 10:00
// and Later Hearth at 12:00, on a grid whose first hour is 10:00. The spec
// puts them back there when it finishes, and again if it fails, so a rerun
// or a CI retry starts from those hours.
const TIMETABLE_URL = "/panel/event/shared-hearth/timetable/";
const PUBLIC_URL = "/event/shared-hearth/";
const ROOM = "Hearth Room";
const MORNING = "Morning Hearth";
const LATER = "Later Hearth";
const MORNING_AT = 0;
const LATER_AT = 120;

const fold = (page: Page) => page.locator("#conflicts-fold");
const summary = (page: Page) => fold(page).locator("summary");
const conflicts = (page: Page) => page.locator("#conflict-panel");
const room = (page: Page) => page.getByRole("group", { name: ROOM });
const block = (page: Page, title: string) => room(page).getByRole("button", { name: title });

const openConflicts = async (page: Page): Promise<void> => {
  if ((await fold(page).getAttribute("open")) === null) await summary(page).click();
};

const minutesOf = async (page: Page, title: string): Promise<number> =>
  Number(await block(page, title).getAttribute("data-start-minutes"));

const dragBy = async (page: Page, title: string, minutes: number): Promise<void> => {
  const card = block(page, title);
  await expect(card).toBeVisible();
  const box = (await card.boundingBox())!;
  const duration = Number(await card.getAttribute("data-duration-minutes"));
  const minutePx = box.height / duration;
  const grab = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
  await page.mouse.move(grab.x, grab.y);
  await page.mouse.down();
  await page.mouse.move(grab.x, grab.y + minutes * minutePx, { steps: 12 });
};

const assignResponse = (page: Page) =>
  page.waitForResponse(
    (response) => response.url().includes("/do/assign/") && response.request().method() === "POST",
  );

const moveTo = async (page: Page, title: string, target: number): Promise<void> => {
  await page.mouse.up();
  const delta = target - (await minutesOf(page, title));
  if (delta === 0) return;
  await dragBy(page, title, delta);
  const posted = assignResponse(page);
  await page.mouse.up();
  expect((await posted).status()).toBe(204);
  await expect.poll(async () => minutesOf(page, title)).toBe(target);
};

const restoreSeed = async (page: Page): Promise<void> => {
  await page.goto(TIMETABLE_URL);
  await moveTo(page, MORNING, MORNING_AT);
  await moveTo(page, LATER, LATER_AT);
};

test.describe("Room overlap on the timetable", () => {
  test.use({ storageState: managerState });

  test("moving onto another session in the room warns, places, and clears again", async ({
    page,
  }, testInfo) => {
    try {
      await restoreSeed(page);
      await expect(summary(page)).toContainText("All clear");

      await dragBy(page, LATER, MORNING_AT - LATER_AT);
      await expect(page.getByText("Room taken")).toBeVisible();
      const onto = assignResponse(page);
      await page.mouse.up();
      expect((await onto).status()).toBe(204);

      await expect(block(page, MORNING)).toBeVisible();
      await expect(block(page, LATER)).toBeVisible();
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
      await moveTo(page, MORNING, LATER_AT);
      await expect(block(page, MORNING)).toBeVisible();
      await expect(block(page, LATER)).toBeVisible();
      await expect(summary(page)).toContainText("All clear");
      await expect(conflicts(page)).not.toContainText("Room occupied by");
      await attachArtifacts(testInfo, {
        name: "room-overlap-cleared",
        region: page.getByRole("main"),
        facts: { room: ROOM, warning: "All clear" },
      });
    } finally {
      await restoreSeed(page);
    }
  });
});
