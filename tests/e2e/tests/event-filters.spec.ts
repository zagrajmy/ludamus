import { type Locator, type Page } from "@playwright/test";

import { expect, test } from "./helpers/fixtures";

const MOBILE_WIDTH = 375;
// The dense seeded event, on the canonical path: /chronology/event/<slug>/ is
// a permanent redirect kept for links shared before that segment was dropped.
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

    // The dense event is the one that carries all three controls: the view
    // switcher only appears where there is a second layout to switch to.
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

  test("filters down to the sessions that take enrollment", async ({ page }) => {
    await page.goto("/event/autumn-open/");

    const card = (title: string) => page.locator(".session", { hasText: title });

    await page.getByRole("button", { name: "Filters" }).click();
    await page.getByRole("checkbox", { name: "Only with enrollment" }).check();

    await expect(card("Mega Strategy Lab")).toBeVisible();
    await expect(card("Przygoda w Mieście Neonów")).toBeVisible();
    // Seeded with no participants limit: a drop-in nobody signs up for.
    await expect(card("Cozy Storytellers Circle")).toBeHidden();
    await expect(page.locator("#active-filter-chips")).toContainText("Only with enrollment");
  });

  test("hides a select field the schedule gives nothing to pick between", async ({ page }) => {
    await page.goto("/event/autumn-open/");
    await page.getByRole("button", { name: "Filters" }).click();

    // Both fields are public selects on this event, so both reach the panel.
    // Only Mood is answered two ways; Format, which nobody answered, would be
    // a select whose one option narrows nothing.
    await expect(page.getByRole("combobox", { name: "Mood" })).toBeVisible();
    await expect(page.locator("#tag-filter-format")).toHaveCount(0);
    // Track clears the same bar, through the same server-side rule.
    await expect(page.locator("#tag-filter-__track")).toHaveCount(0);
  });

  test("states the room size while the enrollment window is shut", async ({ page }) => {
    // The closed-enrollment event has no enrollment window at all, so nothing
    // here can say "spots left" — the seats a session holds is what is left to
    // tell, and it is the size, not the remainder.
    await page.goto("/event/closed-enrollment/");

    const card = (title: string) => page.locator(".session", { hasText: title });
    await expect(card("Late Resignation Demo 1")).toContainText("5 seats");
    await expect(card("Late Resignation Demo 1")).not.toContainText("spots left");
    // Seeded with a single seat: the other side of the plural.
    await expect(card("Late Waiting List Demo 1")).toContainText("1 seat");
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
  const denseEventUrl = `${DENSE_EVENT_URL}?view=rooms`;

  test("collapses the hour rows and room columns a filter empties", async ({ page }) => {
    await page.goto(denseEventUrl);

    const lanes = page.locator(".room-lanes").first();
    // Count what the collapse itself marks, not what is visible: the hour
    // gridlines double as .time-slot-section, whose [hidden] belongs to
    // session-filters.ts, and the head's column rules are drawn at zero height.
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

    // Search one session's title: the rows and columns left holding nothing
    // must collapse rather than keep their server-rendered track size.
    const title = await lanes
      .locator(".room-lanes-cell .session [data-morph='title']")
      .first()
      .innerText();
    await page.locator("#session-filter").fill(title);

    await expect.poll(shownRooms).toBeLessThan(roomCount);
    await expect.poll(shownRows).toBeLessThan(rowCount);

    // Clearing the search restores every track.
    await page.locator("#session-filter").fill("");
    await expect.poll(shownRooms).toBe(roomCount);
    await expect.poll(shownRows).toBe(rowCount);
  });

  // The placement rules moved out of style attributes and into a nonced style
  // element keyed on the data-* indices (issue #743). Nothing server-side can
  // tell whether they still land: a missing rule stacks every tile in the first
  // cell and still renders a plausible-looking page.
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

test.describe("Room filter", () => {
  const denseEventUrl = "/chronology/event/kapitularz-2025-anonymized/";

  test("groups the rooms under their parent space, in panel order", async ({ page }) => {
    await page.goto(denseEventUrl);
    await page.getByRole("button", { name: "Filters" }).click();

    const spaceFilter = page.locator("#space-filter");
    await expect(page.locator("#space-filter-group")).toBeVisible();

    // Panel order, not the alphabet: the tables come before the tents, and
    // "Cosplay Forum" — first alphabetically — is neither. The venue's own
    // option opens each group, so it is not one of the rooms being ordered.
    const options = await spaceFilter
      .locator('optgroup option:not([value^="venue:"])')
      .allInnerTexts();
    expect(options.slice(0, 3)).toEqual(["Miniature Painting", "RPG Table 1", "RPG Table 2"]);
    await expect(spaceFilter.locator("optgroup").first()).toHaveAttribute("label", "Default Area");
  });

  test("narrows the list to every room of the chosen venue", async ({ page }) => {
    await page.goto(denseEventUrl);
    await page.getByRole("button", { name: "Filters" }).click();

    const venue = await page
      .locator('#space-filter option[value^="venue:"]')
      .first()
      .getAttribute("value");
    if (!venue) throw new Error("location filter has no venue option");
    await page.locator("#space-filter").selectOption(venue);

    const visible = page.locator(".session-wrapper:not([hidden])");
    await expect.poll(() => visible.count()).toBeGreaterThan(0);
    for (const card of await visible.locator(".session").all())
      await expect(card).toHaveAttribute("data-venue", venue.replace("venue:", ""));
  });

  test("narrows the list to the chosen room", async ({ page }) => {
    await page.goto(denseEventUrl);
    await page.getByRole("button", { name: "Filters" }).click();

    const total = await page.locator(".session-wrapper").count();
    const room = await page
      .locator('#space-filter option:not([value^="venue:"])')
      .nth(1)
      .getAttribute("value");
    if (!room) throw new Error("room filter has no options");
    await page.locator("#space-filter").selectOption(room);

    const visible = page.locator(".session-wrapper:not([hidden])");
    await expect.poll(() => visible.count()).toBeLessThan(total);
    for (const card of await visible.locator(".session").all())
      await expect(card).toHaveAttribute("data-space", room);
  });
});
