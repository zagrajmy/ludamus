import { type Page } from "@playwright/test";

import { expect, test } from "./helpers/fixtures";

const MOBILE_WIDTH = 375;

test.describe("Event filter panel", () => {
  test("filter panel does not overflow viewport on mobile", async ({ browser }) => {
    const context = await browser.newContext({
      viewport: { width: MOBILE_WIDTH, height: 812 },
    });
    const page = await context.newPage();

    await page.goto("/event/autumn-open/");
    await page.getByRole("button", { name: "Filters" }).click();
    await expect(page.locator("#filter-panel.is-open")).toBeVisible();

    const box = await page.locator("#filter-panel").boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(MOBILE_WIDTH);

    await context.close();
  });

  test("filter panel respects reduced motion", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/event/autumn-open/");

    const filterPanel = page.locator("#filter-panel");
    await expect(filterPanel).toHaveCSS("transform", "none");
    await page.getByRole("button", { name: "Filters" }).click();
    await expect(filterPanel).toHaveCSS("transform", "none");
  });

  test("filters sessions by day and hour on a multi-day event", async ({ page }) => {
    await page.goto("/event/autumn-open/");

    const card = (title: string) => page.locator(".session", { hasText: title });
    await expect(page.locator(".session")).toHaveCount(3);

    await page.getByRole("button", { name: "Filters" }).click();
    await expect(page.locator("#filter-panel.is-open")).toBeVisible();

    // Day and hour filters only surface for multi-day events.
    await expect(page.locator("#day-filter-group")).toBeVisible();
    await expect(page.locator("#hour-filter-group")).toBeVisible();

    // Select the day holding the neon-city adventure by its value (read from the
    // card itself), so the test doesn't depend on option order or the date.
    const neonDay = await card("Przygoda w Mieście Neonów").getAttribute("data-day");
    if (!neonDay) throw new Error("neon-city card is missing data-day");
    await page.locator("#day-filter").selectOption(neonDay);
    await expect(card("Przygoda w Mieście Neonów")).toBeVisible();
    await expect(card("Mega Strategy Lab")).toBeHidden();
    await expect(card("Cozy Storytellers Circle")).toBeHidden();

    // Clearing the day and filtering by start hour narrows to the noon session.
    await page.locator("#day-filter").selectOption("");
    await page.locator("#hour-filter").selectOption("12:00");
    await expect(card("Cozy Storytellers Circle")).toBeVisible();
    await expect(card("Mega Strategy Lab")).toBeHidden();
    await expect(card("Przygoda w Mieście Neonów")).toBeHidden();
  });

  test("filters by host name case-insensitively", async ({ page }) => {
    await page.goto("/event/autumn-open/");

    const card = (title: string) => page.locator(".session", { hasText: title });

    // "Alex Morgan" hosts Mega Strategy Lab; a lowercase query must still match.
    await page.locator("#session-filter").fill("alex");
    await expect(card("Mega Strategy Lab")).toBeVisible();
    await expect(card("Cozy Storytellers Circle")).toBeHidden();
  });
});

test.describe("Event fuzzy search", () => {
  // Each session card exposes an accessible link "Open details for <title>",
  // so we can assert on cards by role + name rather than CSS classes.
  const card = (page: Page, title: string) =>
    page.getByRole("link", { name: `Open details for ${title}` });

  const searchBox = (page: Page) => page.getByRole("textbox", { name: "Search sessions..." });

  const MEGA = "Mega Strategy Lab";
  const COZY = "Cozy Storytellers Circle";
  const NEON = "Przygoda w Mieście Neonów";

  test.beforeEach(async ({ page }) => {
    await page.goto("/event/autumn-open/");
    await expect(card(page, NEON)).toBeVisible();
    await expect(card(page, MEGA)).toBeVisible();
  });

  test("matches multiple tokens across title and host, ignoring diacritics", async ({ page }) => {
    // "Przygoda w Mieście Neonów" hosted by "Radek Włodarczyk": tokens span the
    // title (sans diacritics) and the host name.
    await searchBox(page).fill("przygoda neonow radek");

    await expect(card(page, NEON)).toBeVisible();
    await expect(card(page, MEGA)).toBeHidden();
    await expect(card(page, COZY)).toBeHidden();
  });

  test('folds the Polish "ł", which NFD leaves intact', async ({ page }) => {
    // Host "Radek Włodarczyk": "ł" has no NFD decomposition, so the
    // stroke-less query "wlodarczyk" only matches with the explicit fold.
    await searchBox(page).fill("wlodarczyk");

    await expect(card(page, NEON)).toBeVisible();
    await expect(card(page, MEGA)).toBeHidden();
  });

  test("matches a token from the title and a token from the host", async ({ page }) => {
    await searchBox(page).fill("mega alex");

    await expect(card(page, MEGA)).toBeVisible();
    await expect(card(page, NEON)).toBeHidden();
  });

  test("matches a word that only appears in the description", async ({ page }) => {
    // "Jumanji" is in the neon session's blurb, not its title or host.
    await searchBox(page).fill("jumanji");

    await expect(card(page, NEON)).toBeVisible();
    await expect(card(page, MEGA)).toBeHidden();
    await expect(card(page, COZY)).toBeHidden();
  });

  test("combines a title token with a description token", async ({ page }) => {
    // "neonow" comes from the title, "jumanji" from the description.
    await searchBox(page).fill("neonow jumanji");

    await expect(card(page, NEON)).toBeVisible();
    await expect(card(page, MEGA)).toBeHidden();
  });

  test("shows the empty state when nothing matches", async ({ page }) => {
    await searchBox(page).fill("zzzznomatch");

    await expect(card(page, MEGA)).toBeHidden();
    await expect(page.getByText("No sessions match your filters")).toBeVisible();
  });
});

test.describe("Rooms view filtering", () => {
  const denseEventUrl = "/chronology/event/kapitularz-2025-anonymized/?view=rooms";

  test("collapses the hour rows and room columns a filter empties", async ({ page }) => {
    await page.goto(denseEventUrl);

    const grid = page.locator(".room-lanes-body").first();
    const gridHeight = async (): Promise<number> => (await grid.boundingBox())!.height;
    const roomNames = page.locator(".room-lanes-head [data-lane-col]:not(.room-lanes-rule)");
    const shownRooms = async (): Promise<number> => roomNames.locator("visible=true").count();

    await expect(grid).toBeVisible();
    const fullHeight = await gridHeight();
    const roomCount = await roomNames.count();
    expect(roomCount).toBeGreaterThan(1);

    // Search one session's title: the rows and columns left holding nothing
    // must collapse rather than keep their server-rendered track size.
    const title = await page
      .locator(".room-lanes-cell .session [data-morph='title']")
      .first()
      .innerText();
    await page.locator("#session-filter").fill(title);

    await expect.poll(shownRooms).toBeLessThan(roomCount);
    await expect.poll(gridHeight).toBeLessThan(fullHeight / 2);

    // Clearing the search restores every track.
    await page.locator("#session-filter").fill("");
    await expect.poll(shownRooms).toBe(roomCount);
    await expect.poll(gridHeight).toBe(fullHeight);
  });
});
