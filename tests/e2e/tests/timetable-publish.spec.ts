import { type Browser, type Page } from "@playwright/test";

import { attachArtifacts } from "./helpers/artifacts";
import { managerState } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

// NOTE: gilded-bazaar holds one accepted session nobody has placed, one room
// on an eight-hour day (bootstrap_data.py). The test places the
// session and takes it off again; afterEach takes it off if a failure left it
// placed, so a retry starts from the seed.
const TIMETABLE_URL = "/panel/event/gilded-bazaar/timetable/";
const EVENT_URL = "/event/gilded-bazaar/";
const TITLE = "Brass Lantern Tale";

const toAssign = (page: Page) => page.getByRole("region", { name: "Sessions to assign" });
const room = (page: Page) =>
  page.getByRole("region", { name: "Schedule" }).getByRole("group", { name: "Brass Room" });

// NOTE: the event page is cached in the browser for three minutes, so each
// look is a fresh visitor, the way someone arriving after the change sees it.
const visitPublicPage = async (browser: Browser) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(EVENT_URL);
  return { context, page };
};

const unassign = async (page: Page) => {
  await room(page).getByRole("button", { name: TITLE }).click();
  await page.getByRole("button", { name: "Unassign" }).click();
  await expect(toAssign(page).getByRole("button", { name: TITLE })).toBeVisible();
  await expect(room(page).getByRole("button", { name: TITLE })).toHaveCount(0);
};

test.use({ storageState: managerState });

test.afterEach(async ({ page }) => {
  await page.goto(TIMETABLE_URL);
  await expect(room(page)).toBeVisible();
  if ((await room(page).getByRole("button", { name: TITLE }).count()) > 0) await unassign(page);
});

test("placing an accepted session publishes it on the event page, and taking it off unpublishes it", async ({
  page,
  browser,
}, testInfo) => {
  const before = await visitPublicPage(browser);
  await expect(before.page.getByRole("link", { name: `Open details for ${TITLE}` })).toHaveCount(0);
  await before.context.close();

  await page.goto(TIMETABLE_URL);
  await toAssign(page).getByRole("button", { name: TITLE }).click();
  await expect(page.getByRole("heading", { name: "Session details" })).toBeVisible();
  await page.getByRole("button", { name: "Assign", exact: true }).click();
  await expect(page.getByText("Click a position on the grid")).toBeVisible();
  // The top of the column is the start of the slot.
  await room(page).click({ position: { x: 20, y: 5 } });
  await expect(room(page).getByRole("button", { name: TITLE })).toBeVisible();
  await expect(toAssign(page).getByRole("button", { name: TITLE })).toHaveCount(0);

  const placed = await visitPublicPage(browser);
  // NOTE: the card's description sits above its stretched link, so a pointer
  // click lands on the text; the keyboard reaches the link itself.
  await placed.page.getByRole("link", { name: `Open details for ${TITLE}` }).press("Enter");
  const details = placed.page.getByRole("dialog", { name: TITLE });
  await expect(details).toContainText("Brass Room");
  await expect(details).toContainText("10:00–12:00");
  await attachArtifacts(testInfo, {
    name: "timetable-publish",
    region: details,
    facts: { session: TITLE, room: "Brass Room", time: "10:00–12:00" },
  });
  await placed.context.close();

  await unassign(page);
  const removed = await visitPublicPage(browser);
  await expect(removed.page.getByRole("link", { name: `Open details for ${TITLE}` })).toHaveCount(
    0,
  );
  await removed.context.close();
});
