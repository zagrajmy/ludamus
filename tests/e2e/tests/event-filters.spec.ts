import { type Locator, type Page } from "@playwright/test";

import { expect, test } from "./helpers/fixtures";

const MOBILE_WIDTH = 375;
const DENSE_EVENT_URL = "/event/kapitularz-2025-anonymized/";

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

  test("the toolbar controls line up with the search field on mobile", async ({ browser }) => {
    const context = await browser.newContext({
      viewport: { width: MOBILE_WIDTH, height: 812 },
    });
    const page = await context.newPage();

    await page.goto(DENSE_EVENT_URL);

    const box = async (locator: Locator) => {
      const rect = await locator.boundingBox();
      if (!rect) throw new Error("toolbar control is not laid out");
      return rect;
    };
    const search = await box(page.getByRole("textbox", { name: "Search sessions..." }));
    const filters = await box(page.getByRole("button", { name: "Filters" }));
    const tabs = await box(page.getByRole("tablist"));

    for (const control of [filters, tabs]) {
      expect(Math.abs(control.height - search.height)).toBeLessThanOrEqual(1);
      expect(Math.abs(control.y - search.y)).toBeLessThanOrEqual(1);
    }

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

    await expect(page.locator("#day-filter-group")).toBeVisible();
    await expect(page.locator("#hour-filter-group")).toBeVisible();

    const neonDay = await card("Przygoda w Mieście Neonów").getAttribute("data-day");
    if (!neonDay) throw new Error("neon-city card is missing data-day");
    await page.locator("#day-filter").selectOption(neonDay);
    await expect(card("Przygoda w Mieście Neonów")).toBeVisible();
    await expect(card("Mega Strategy Lab")).toBeHidden();
    await expect(card("Cozy Storytellers Circle")).toBeHidden();

    await page.locator("#day-filter").selectOption("");
    await page.locator("#hour-filter").selectOption("12:00");
    await expect(card("Cozy Storytellers Circle")).toBeVisible();
    await expect(card("Mega Strategy Lab")).toBeHidden();
    await expect(card("Przygoda w Mieście Neonów")).toBeHidden();
  });

  test("filters down to the sessions that take enrollment", async ({ page }) => {
    await page.goto("/event/autumn-open/");

    const card = (title: string) => page.locator(".session", { hasText: title });

    await page.getByRole("button", { name: "Filters" }).click();
    await page.getByText("Only with enrollment").click();
    await expect(page.locator("#filter-panel.is-open")).toBeVisible();
    await expect(page.getByRole("checkbox", { name: "Only with enrollment" })).toBeChecked();

    await expect(card("Mega Strategy Lab")).toBeVisible();
    await expect(card("Przygoda w Mieście Neonów")).toBeVisible();
    await expect(card("Cozy Storytellers Circle")).toBeHidden();
    await expect(page.locator("#active-filter-chips")).toContainText("Only with enrollment");
  });

  test("hides a select field the schedule gives nothing to pick between", async ({ page }) => {
    await page.goto("/event/autumn-open/");
    await page.getByRole("button", { name: "Filters" }).click();

    await expect(page.getByRole("combobox", { name: "Mood" })).toBeVisible();
    await expect(page.locator("#tag-filter-format")).toHaveCount(0);
    await expect(page.locator("#tag-filter-__track")).toHaveCount(0);
  });

  test("states the room size while the enrollment window is shut", async ({ page }) => {
    await page.goto("/event/closed-enrollment/");

    const card = (title: string) => page.locator(".session", { hasText: title });
    await expect(card("Late Resignation Demo 1")).toContainText("5 seats");
    await expect(card("Late Resignation Demo 1")).not.toContainText("spots left");
    await expect(card("Late Waiting List Demo 1")).toContainText("1 seat");
  });

  test("filters by host name case-insensitively", async ({ page }) => {
    await page.goto("/event/autumn-open/");

    const card = (title: string) => page.locator(".session", { hasText: title });

    await page.locator("#session-filter").fill("alex");
    await expect(card("Mega Strategy Lab")).toBeVisible();
    await expect(card("Cozy Storytellers Circle")).toBeHidden();
  });
});

test.describe("Event fuzzy search", () => {
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
    await searchBox(page).fill("przygoda neonow radek");

    await expect(card(page, NEON)).toBeVisible();
    await expect(card(page, MEGA)).toBeHidden();
    await expect(card(page, COZY)).toBeHidden();
  });

  test('folds the Polish "ł", which NFD leaves intact', async ({ page }) => {
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
    await searchBox(page).fill("jumanji");

    await expect(card(page, NEON)).toBeVisible();
    await expect(card(page, MEGA)).toBeHidden();
    await expect(card(page, COZY)).toBeHidden();
  });

  test("combines a title token with a description token", async ({ page }) => {
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
  const denseEventUrl = `${DENSE_EVENT_URL}?view=rooms`;

  test("collapses the hour rows and room columns a filter empties", async ({ page }) => {
    await page.goto(denseEventUrl);

    const lanes = page.locator(".room-lanes").first();
    const rowSelector = ".room-lanes-time[data-lane-row]";
    const roomSelector = ".room-lanes-head [data-lane-col]";
    const shownRows = async (): Promise<number> =>
      lanes.locator(`${rowSelector}:not(.room-lanes-collapsed)`).count();
    const shownRooms = async (): Promise<number> =>
      lanes.locator(`${roomSelector}:not(.room-lanes-collapsed)`).count();

    await expect(lanes).toBeVisible();
    const rowCount = await lanes.locator(rowSelector).count();
    const roomCount = await lanes.locator(roomSelector).count();
    expect(rowCount).toBeGreaterThan(1);
    expect(roomCount).toBeGreaterThan(1);

    const title = await lanes
      .locator(".room-lanes-cell .session [data-morph='title']")
      .first()
      .innerText();
    await page.locator("#session-filter").fill(title);

    await expect.poll(shownRooms).toBeLessThan(roomCount);
    await expect.poll(shownRows).toBeLessThan(rowCount);

    await page.locator("#session-filter").fill("");
    await expect.poll(shownRooms).toBe(roomCount);
    await expect.poll(shownRows).toBe(rowCount);
  });

  test("places each tile in the column and row its data attributes name", async ({ page }) => {
    await page.goto(denseEventUrl);

    const cells = page.locator(".room-lanes-body .room-lanes-cell");
    await expect(cells.first()).toBeVisible();

    const placements = await cells.evaluateAll((nodes) =>
      nodes.map((node) => {
        const style = globalThis.getComputedStyle(node);
        const { tileCol, tileRow, tileSpan } = (node as HTMLElement).dataset;
        return {
          expected: [`${Number(tileCol) + 1}`, `${tileRow}`, `span ${tileSpan}`],
          actual: [style.gridColumnStart, style.gridRowStart, style.gridRowEnd],
        };
      }),
    );

    expect(placements.length).toBeGreaterThan(1);
    for (const { expected, actual } of placements) expect(actual).toEqual(expected);
  });
});
