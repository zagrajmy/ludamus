import { type Locator, type Page } from "@playwright/test";
import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";

// Driven by scripts/bootstrap_worst_case.py: realistic worst-case data (long
// hyphenated names, a 57-character room name, a 61-character track, 1,284
// unread notifications) viewed by its manager on a phone.
test.use({
  storageState: path.join(__dirname, "..", ".auth-state-worst.json"),
  viewport: { width: 390, height: 844 },
});

const EVENT = "/event/worst-case/";
const PANEL = "/panel/event/worst-case";

const fullyShown = (locator: Locator) =>
  locator.evaluate((el) => el.clientWidth > 0 && el.scrollWidth <= el.clientWidth);

const overflowsViewport = (page: Page) =>
  page.evaluate(() => {
    const scroller = document.getElementById("app-scroll") ?? document.documentElement;
    return scroller.scrollWidth > window.innerWidth;
  });

test("a card's room stays readable when the venue name is long", async ({ page }, testInfo) => {
  await page.goto(EVENT);
  const card = page.getByRole("article").filter({ hasText: "Warsztaty malowania figurek" });
  const room = card.getByRole("link", { name: "Hol", exact: true });

  await expect(room).toBeVisible();
  expect(await fullyShown(room)).toBe(true);

  await attachArtifacts(testInfo, {
    name: "worst-case-card",
    region: card,
    facts: { room: await room.textContent(), fullyShown: true },
  });
});

test("the unread badge caps at 99+ and the label keeps the count", async ({ page }) => {
  await page.goto(EVENT);
  const bell = page.getByRole("button", { name: "Notifications (1284 unread)" });

  await expect(bell).toHaveText("99+");
});

test("a long proposal title keeps its breadcrumb and actions on a phone", async ({
  page,
}, testInfo) => {
  await page.goto(`${PANEL}/proposals/`);
  expect(await overflowsViewport(page)).toBe(false);

  await page.getByRole("link", { name: /^Q3 Board Deck/ }).click();
  const eventCrumb = page.getByRole("link", { name: /^Międzynarodowy Festiwal/ });

  await expect(page.getByRole("heading", { level: 2, name: /^Q3 Board Deck/ })).toBeVisible();
  await expect(eventCrumb).toBeVisible();
  // Squeezed beside the actions, the trail ran one word per line in ~100px.
  const crumbWidth = (await eventCrumb.boundingBox())?.width;
  expect(crumbWidth).toBeGreaterThan(250);
  expect(await overflowsViewport(page)).toBe(false);

  await attachArtifacts(testInfo, {
    name: "worst-case-proposal-header",
    region: page.getByRole("main"),
    facts: { crumbWidth, overflowsViewport: false },
  });
});

test("a long room name keeps its row in the venue tree", async ({ page }, testInfo) => {
  await page.goto(`${PANEL}/venues/`);
  // The innermost list item holding the name is the room's own row.
  const row = page
    .getByRole("listitem")
    .filter({ has: page.getByTitle(/^Sala nr 12/) })
    .last();
  const name = row.getByTitle(/^Sala nr 12/);
  const edit = row.getByRole("link", { name: /^Edit Sala nr 12/ });
  const track = row.getByTitle(/^Blok programowy/);

  expect((await name.boundingBox())?.width).toBeGreaterThan(120);
  const trackBox = await track.boundingBox();
  const editBox = await edit.boundingBox();
  if (!trackBox || !editBox) throw new Error("The row needs its track pill and edit link");
  expect(trackBox.x + trackBox.width).toBeLessThanOrEqual(editBox.x);
  expect(await overflowsViewport(page)).toBe(false);

  await attachArtifacts(testInfo, {
    name: "worst-case-venue-row",
    region: row,
    facts: { nameWidth: (await name.boundingBox())?.width },
  });
});

test("a one-seat room's conflict reads in the singular", async ({ page }) => {
  await page.goto(`${PANEL}/timetable/`);

  await expect(page.getByText("Room fits 1 person, session requires 1284")).toBeVisible();
});
