import { type Locator } from "@playwright/test";

import { signInAsManager } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

// On a phone the ledger runs to the screen edges with the hour rail in its
// right-hand column. The header, the toolbar and the rows' icons share one
// content column, and the rail's first day label reads level with the first
// day heading.
test.use({ viewport: { width: 375, height: 812 } });

const DENSE_EVENT = "/event/kapitularz-2025-anonymized/";

const box = async (locator: Locator) => {
  const found = await locator.boundingBox();
  expect(found).not.toBeNull();
  return found!;
};

const textMiddle = (locator: Locator): Promise<number> =>
  locator.evaluate((el) => {
    const range = document.createRange();
    range.selectNodeContents(el);
    const rect = range.getBoundingClientRect();
    return (rect.top + rect.bottom) / 2;
  });

test("the toolbar, the day chevron and the bookmarks end on one edge", async ({
  page,
}, testInfo) => {
  await signInAsManager(page);
  await page.goto(DENSE_EVENT);
  const views = page.getByRole("tablist", { name: "Schedule view" });
  const firstDay = page.locator("[data-schedule-day]").first();
  const dayToggle = firstDay.getByRole("button", { name: /Monday/ });
  const chevron = dayToggle.locator("svg");
  const bookmark = firstDay.getByRole("button", { name: "Bookmark session" }).first();
  const rail = page.getByRole("navigation", { name: "Jump to time" });
  const firstRailDay = rail.locator("span").first();
  const dayName = dayToggle.locator("[data-day-name]");

  const viewsBox = await box(views);
  const toolbarEnd = viewsBox.x + viewsBox.width;
  const chevronBox = await box(chevron);
  const bookmarkBox = await box(bookmark.locator("svg:visible"));
  const facts = {
    toolbarEnd,
    chevronEnd: chevronBox.x + chevronBox.width,
    chevronAxis: chevronBox.x + chevronBox.width / 2,
    bookmarkAxis: bookmarkBox.x + bookmarkBox.width / 2,
    railDayMiddle: await textMiddle(firstRailDay),
    dayHeadingMiddle: await textMiddle(dayName),
  };

  expect(Math.abs(facts.toolbarEnd - facts.chevronEnd)).toBeLessThanOrEqual(1);
  expect(Math.abs(facts.bookmarkAxis - facts.chevronAxis)).toBeLessThanOrEqual(1);
  expect(Math.abs(facts.railDayMiddle - facts.dayHeadingMiddle)).toBeLessThanOrEqual(1);

  // The region runs the whole programme long; the viewport holding its top
  // is what shows the alignment.
  await page.locator("#schedule-region").evaluate((el) => el.scrollIntoView());
  await testInfo.attach("schedule-phone-alignment.png", {
    body: await page.screenshot(),
    contentType: "image/png",
  });
  await testInfo.attach("schedule-phone-alignment.json", {
    body: `${JSON.stringify(facts, null, 2)}\n`,
    contentType: "application/json",
  });
});

test("the rooms grid keeps its rail on the sticky day bar", async ({ page }) => {
  await page.goto(`${DENSE_EVENT}?view=rooms`);
  const rail = page.getByRole("navigation", { name: "Jump to time" });
  const dayBar = page.locator("[data-room-lanes-day-current] [data-day-name]");

  const railDayMiddle = await textMiddle(rail.locator("span").first());
  const barDayMiddle = await textMiddle(dayBar);
  expect(Math.abs(railDayMiddle - barDayMiddle)).toBeLessThan(3);
});
