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
    await page.getByRole("button", { exact: true, name: "Filters" }).click();
    await expect(page.locator("#filter-panel.is-open")).toBeVisible();

    const box = await page.locator("#filter-panel").boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(MOBILE_WIDTH);

    await context.close();
  });

  test("gives the filters the whole screen on a phone", async ({ browser }) => {
    // A short viewport is where the dropdown used to fail outright: anchored
    // under a trigger that sits low on the page, it landed past the bottom
    // edge and its controls could not be reached at all.
    const context = await browser.newContext({
      viewport: { width: MOBILE_WIDTH, height: 700 },
    });
    const page = await context.newPage();

    await page.goto("/event/autumn-open/");
    await page.getByRole("button", { exact: true, name: "Filters" }).click();

    // Polled, not read once: the panel animates in, and its box is still
    // travelling for a third of a second after it becomes visible.
    const trigger = page.getByRole("button", { exact: true, name: "Filters" });
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
    const panel = page.locator("#filter-panel");
    await expect.poll(async () => (await panel.boundingBox())?.y).toBe(0);
    await expect.poll(async () => (await panel.boundingBox())?.height).toBe(700);

    // The control that was out of reach before, exercised the way a person
    // would: if it is off-screen, this click times out.
    await page.locator("[data-combobox-input]").first().click();
    await expect(page.getByRole("listbox")).toBeVisible();
    // Escape unwinds one layer at a time: the list goes, the sheet stays.
    await page.keyboard.press("Escape");
    await expect(page.getByRole("listbox")).toBeHidden();
    await expect(trigger).toHaveAttribute("aria-expanded", "true");

    // A sheet covers its own trigger and leaves no outside to tap, so the way
    // out has to be inside it.
    await page.getByRole("button", { name: "Close filters" }).click();
    await expect(trigger).toHaveAttribute("aria-expanded", "false");

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
    const search = await box(page.getByRole("textbox", { name: "Search by name or text..." }));
    const filters = await box(page.getByRole("button", { exact: true, name: "Filters" }));
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
    await page.getByRole("button", { exact: true, name: "Filters" }).click();
    await expect(filterPanel).toHaveCSS("transform", "none");
  });

  test("filters sessions by day and hour on a multi-day event", async ({ page }) => {
    await page.goto("/event/autumn-open/");

    const card = (title: string) => page.locator(".session", { hasText: title });
    await expect(page.locator(".session")).toHaveCount(3);

    await page.getByRole("button", { exact: true, name: "Filters" }).click();
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

    await page.getByRole("button", { exact: true, name: "Filters" }).click();
    await page.locator("label").filter({ hasText: "Only with enrollment" }).click();
    await expect(page.locator("#filter-panel.is-open")).toBeVisible();
    await expect(page.getByRole("checkbox", { name: "Only with enrollment" })).toBeChecked();

    await expect(card("Mega Strategy Lab")).toBeVisible();
    await expect(card("Przygoda w Mieście Neonów")).toBeVisible();
    await expect(card("Cozy Storytellers Circle")).toBeHidden();
    await expect(page.locator("#active-filter-chips")).toContainText("Only with enrollment");
  });

  test("hides a select field the schedule gives nothing to pick between", async ({ page }) => {
    await page.goto("/event/autumn-open/");
    await page.getByRole("button", { exact: true, name: "Filters" }).click();

    // A filter that survives has something to pick: the two answered moods.
    await expect(page.getByRole("combobox", { name: "Mood" })).toBeVisible();
    await expect(page.locator("#tag-filter-mood").locator("option")).toHaveText([
      "All Mood",
      "Cosy",
      "Tense",
    ]);
    await expect(page.locator("#tag-filter-format")).toHaveCount(0);
    await expect(page.locator("#tag-filter-__track")).toHaveCount(0);
  });

  test("the track filter offers the tracks the schedule uses", async ({ page }) => {
    await page.goto(DENSE_EVENT_URL);

    // Track and category options are rendered by the server like every other
    // filter's; the client only drops the ones no session carries.
    const trackFilter = page.locator("#tag-filter-__track");
    await expect(trackFilter.locator("option")).toHaveText([
      "All tracks",
      "Contests",
      "Cosplay",
      "Miniature Painting",
      "Publisher Tables",
      "RPG",
      "Workshops",
    ]);

    const shown = page.locator(".session:visible");
    const total = await shown.count();
    await trackFilter.selectOption("Cosplay");

    await expect(shown).not.toHaveCount(total);
    await expect(shown.first()).toContainText("Cosplay");
  });

  test("states the room size while the enrollment window is shut", async ({ page }) => {
    await page.goto("/event/closed-enrollment/");

    const card = (title: string) => page.locator(".session", { hasText: title });
    await expect(card("Late Resignation Demo 1")).toContainText("5 seats");
    await expect(card("Late Resignation Demo 1")).not.toContainText("spots left");
    await expect(card("Late Waiting List Demo 1")).toContainText("1 seat");
  });

  test("offers a field's used choices only, never a written-in value", async ({ page }) => {
    await page.goto("/event/autumn-open/");

    // "Tone" allows custom answers: Mega Strategy Lab picked "Lighthearted",
    // the neon session picked "Grimdark" and wrote in "kalamburowy" beside it,
    // and "Solemn" is a choice nobody picked.
    const toneFilter = page.locator("#tag-filter-tone");
    await expect(toneFilter.locator("option")).toHaveText(["All Tone", "Lighthearted", "Grimdark"]);

    const card = (title: string) => page.locator(".session", { hasText: title });
    await toneFilter.selectOption("Lighthearted");
    await expect(card("Mega Strategy Lab")).toBeVisible();
    await expect(card("Przygoda w Mieście Neonów")).toBeHidden();
  });

  test("finds a written-in field value through the search box", async ({ page }) => {
    await page.goto("/event/autumn-open/");

    const card = (title: string) => page.locator(".session", { hasText: title });
    await page.locator("#session-filter").fill("kalamburowy");

    await expect(card("Przygoda w Mieście Neonów")).toBeVisible();
    await expect(card("Mega Strategy Lab")).toBeHidden();
  });

  test("filters by host name case-insensitively", async ({ page }) => {
    await page.goto("/event/autumn-open/");

    const card = (title: string) => page.locator(".session", { hasText: title });

    await page.locator("#session-filter").fill("alex");
    await expect(card("Mega Strategy Lab")).toBeVisible();
    await expect(card("Cozy Storytellers Circle")).toBeHidden();
  });

  test("the host filter offers the schedule's hosts and narrows to one", async ({ page }) => {
    await page.goto("/event/autumn-open/");
    await page.getByRole("button", { exact: true, name: "Filters" }).click();

    const hostFilter = page.getByRole("combobox", { name: "Host" });
    await hostFilter.click();
    await expect(page.getByRole("listbox", { name: "Host" }).getByRole("option")).toHaveText([
      "All hosts",
      "Alex Morgan",
      "Priya Chen",
      "Radek Włodarczyk",
    ]);

    const card = (title: string) => page.getByRole("link", { name: `Open details for ${title}` });
    await page.getByRole("option", { name: "Priya Chen" }).click();
    await expect(hostFilter).toHaveValue("Priya Chen");
    await expect(card("Cozy Storytellers Circle")).toBeVisible();
    await expect(card("Mega Strategy Lab")).toBeHidden();
    await expect(card("Przygoda w Mieście Neonów")).toBeHidden();
  });

  test("the host combobox narrows as you type and commits on Enter", async ({ page }) => {
    await page.goto("/event/autumn-open/");
    await page.getByRole("button", { exact: true, name: "Filters" }).click();

    const hostFilter = page.getByRole("combobox", { name: "Host" });
    const options = page.getByRole("listbox", { name: "Host" }).getByRole("option");
    await hostFilter.fill("chen");
    await expect(options).toHaveText(["Priya Chen"]);

    // DOM focus stays on the input; the active option is named instead.
    await hostFilter.press("ArrowDown");
    await expect(hostFilter).toHaveAttribute("aria-activedescendant", /host-filter-option-/);
    await expect(hostFilter).toBeFocused();

    await hostFilter.press("Enter");
    await expect(hostFilter).toHaveValue("Priya Chen");
    await expect(hostFilter).toHaveAttribute("aria-expanded", "false");
    const card = (title: string) => page.getByRole("link", { name: `Open details for ${title}` });
    await expect(card("Cozy Storytellers Circle")).toBeVisible();
    await expect(card("Mega Strategy Lab")).toBeHidden();
  });

  test("the host combobox says when nothing matches, and Escape restores the pick", async ({
    page,
  }) => {
    await page.goto("/event/autumn-open/");
    await page.getByRole("button", { exact: true, name: "Filters" }).click();

    const hostFilter = page.getByRole("combobox", { name: "Host" });
    await hostFilter.fill("chen");
    await page.getByRole("option", { name: "Priya Chen" }).click();

    await hostFilter.fill("zzzznomatch");
    await expect(page.getByText("No host matches your search.")).toBeVisible();

    // A half-typed query is not a value: Escape puts the committed one back.
    await hostFilter.press("Escape");
    await expect(hostFilter).toHaveValue("Priya Chen");
    await expect(hostFilter).toHaveAttribute("aria-expanded", "false");

    // Pressing it again on a closed list clears the pick, as the pattern says.
    await hostFilter.press("Escape");
    await expect(hostFilter).toHaveValue("All hosts");
  });

  test("the host combobox folds diacritics like the search box does", async ({ page }) => {
    await page.goto("/event/autumn-open/");
    await page.getByRole("button", { exact: true, name: "Filters" }).click();

    const hostFilter = page.getByRole("combobox", { name: "Host" });
    await hostFilter.fill("wlodarczyk");
    await expect(page.getByRole("listbox", { name: "Host" }).getByRole("option")).toHaveText([
      "Radek Włodarczyk",
    ]);
  });

  test("clearing the filters puts the host combobox back to its placeholder", async ({ page }) => {
    await page.goto("/event/autumn-open/");
    await page.getByRole("button", { exact: true, name: "Filters" }).click();

    const hostFilter = page.getByRole("combobox", { name: "Host" });
    await hostFilter.click();
    await page.getByRole("option", { name: "Priya Chen" }).click();
    await expect(hostFilter).toHaveValue("Priya Chen");

    await page.getByRole("button", { name: "Clear all" }).click();
    await expect(hostFilter).toHaveValue("All hosts");
  });

  test("the age filter keeps the sessions that admit the typed age", async ({ page }) => {
    await page.goto("/event/autumn-open/");
    await page.getByRole("button", { exact: true, name: "Filters" }).click();

    // Cozy Storytellers Circle is open to everyone; the other two require 10+.
    const card = (title: string) => page.getByRole("link", { name: `Open details for ${title}` });
    const ageFilter = page.getByRole("spinbutton", { name: "Participant age" });
    await ageFilter.fill("9");
    await expect(card("Cozy Storytellers Circle")).toBeVisible();
    await expect(card("Mega Strategy Lab")).toBeHidden();
    await expect(card("Przygoda w Mieście Neonów")).toBeHidden();
    await expect(page.getByText("Participant age: 9")).toBeVisible();

    await ageFilter.fill("10");
    await expect(card("Mega Strategy Lab")).toBeVisible();
    await expect(card("Przygoda w Mieście Neonów")).toBeVisible();

    // A number input accepts exponent notation; "1e1" must filter as 10,
    // not as parseInt's 1.
    await ageFilter.fill("1e1");
    await expect(card("Mega Strategy Lab")).toBeVisible();
    await expect(card("Przygoda w Mieście Neonów")).toBeVisible();
  });

  test("hides the host filter when every session shares one host", async ({ page }) => {
    await page.goto("/event/closed-enrollment/");
    await page.getByRole("button", { exact: true, name: "Filters" }).click();
    await expect(page.getByRole("button", { exact: true, name: "Filters" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );

    await expect(page.getByRole("combobox", { name: "Host" })).toBeHidden();
  });
});

test.describe("Event fuzzy search", () => {
  const card = (page: Page, title: string) =>
    page.getByRole("link", { name: `Open details for ${title}` });

  const searchBox = (page: Page) =>
    page.getByRole("textbox", { name: "Search by name or text..." });

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

test.describe("Filter state in the URL", () => {
  const card = (page: Page, title: string) => page.locator(".session", { hasText: title });

  test("mirrors active filters into the URL without adding history entries", async ({ page }) => {
    await page.goto("/events/");
    await page.goto("/event/autumn-open/");

    await page.locator("#session-filter").fill("alex");
    await page.getByRole("button", { exact: true, name: "Filters" }).click();
    await page.getByRole("checkbox", { name: "Only with enrollment" }).check();

    // Poll the later edit: the sync that carries it reads every control, so
    // once `enrollment` lands, `q` is in the same write.
    await expect.poll(() => new URL(page.url()).searchParams.get("enrollment")).toBe("1");
    expect(new URL(page.url()).searchParams.get("q")).toBe("alex");

    // The mirror is replaceState-only: Back leaves the page in one step
    // instead of walking through every filter edit.
    await page.goBack();
    expect(new URL(page.url()).pathname).toBe("/events/");
  });

  test("restores filters from a shared URL", async ({ page }) => {
    await page.goto("/event/autumn-open/?hour=12%3A00&q=circle&age=9");

    await expect(card(page, "Cozy Storytellers Circle")).toBeVisible();
    await expect(card(page, "Mega Strategy Lab")).toBeHidden();
    await expect(card(page, "Przygoda w Mieście Neonów")).toBeHidden();

    await expect(page.locator("#session-filter")).toHaveValue("circle");
    await expect(page.getByRole("spinbutton", { name: "Participant age" })).toHaveValue("9");
    await expect(page.locator("#active-filter-chips")).toContainText("12:00");
  });

  test("offers the age ratings the schedule uses, as ratings not numbers", async ({ page }) => {
    await page.goto(DENSE_EVENT_URL);
    await page.getByRole("button", { exact: true, name: "Filters" }).click();

    // "Show me the 18+ programme" is one pick, not a number to guess at, and
    // the list is the event's own ratings rather than every age that exists.
    const rating = page.getByRole("combobox", { name: "Age from" });
    const offered = (await rating.locator("option").allInnerTexts()).slice(1);
    expect(offered.length).toBeGreaterThan(0);
    for (const label of offered) expect(label).toMatch(/^\d+\+$/);
    // Ages, so ordered as numbers — a string sort would put 12+ before 9+.
    const ages = offered.map((label) => Number.parseInt(label, 10));
    expect(ages).toEqual([...ages].sort((a, b) => a - b));
  });

  test("still answers the age-min links people have already shared", async ({ page }) => {
    // "Show me the 18+ programme" is a link that predates this panel, and the
    // param has to keep meaning a floor on the session's own requirement —
    // answering it with its complement would be worse than not answering.
    await page.goto("/event/autumn-open/?age-min=10");

    await expect(card(page, "Mega Strategy Lab")).toBeVisible();
    await expect(card(page, "Przygoda w Mieście Neonów")).toBeVisible();
    await expect(card(page, "Cozy Storytellers Circle")).toBeHidden();
    await expect(page.getByRole("combobox", { name: "Age from" })).toHaveValue("10");
  });

  test("reads the two age bounds as the opposite questions they are", async ({ page }) => {
    await page.goto("/event/autumn-open/");
    await page.getByRole("button", { exact: true, name: "Filters" }).click();

    await page.getByRole("combobox", { name: "Age from" }).selectOption("10");
    await expect(card(page, "Cozy Storytellers Circle")).toBeHidden();
    await expect(card(page, "Mega Strategy Lab")).toBeVisible();

    // The same number in the other box asks who may attend, not what is
    // restricted, so it keeps the unrestricted session and drops nothing.
    await page.getByRole("combobox", { name: "Age from" }).selectOption("");
    await page.getByRole("spinbutton", { name: "Participant age" }).fill("10");
    await expect(card(page, "Cozy Storytellers Circle")).toBeVisible();
    await expect(card(page, "Mega Strategy Lab")).toBeVisible();
  });

  test("drops an unusable age from a shared URL instead of guessing", async ({ page }) => {
    await page.goto("/event/autumn-open/?age=120");

    await expect(card(page, "Cozy Storytellers Circle")).toBeVisible();
    await expect(page.getByRole("spinbutton", { name: "Participant age" })).toHaveValue("");
  });

  test("keeps the mirror through a session modal opening and closing", async ({ page }) => {
    await page.goto("/event/autumn-open/");
    await page.locator("#session-filter").fill("mega");
    await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe("mega");

    // The trigger href is a bare `?session=<pk>`; opening must not cost the
    // URL its filter params, and closing must drop only the session param.
    await page.getByRole("link", { name: "Open details for Mega Strategy Lab" }).click();
    await expect(page.locator("dialog.modal[open]")).toBeVisible();
    await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe("mega");
    expect(new URL(page.url()).searchParams.has("session")).toBe(true);

    await page.keyboard.press("Escape");
    await expect.poll(() => new URL(page.url()).searchParams.has("session")).toBe(false);
    expect(new URL(page.url()).searchParams.get("q")).toBe("mega");
  });

  test("carries filters across the schedule view switch", async ({ page }) => {
    await page.goto(DENSE_EVENT_URL);

    const title = await page.locator(".session").first().getAttribute("data-title");
    if (!title) throw new Error("first session card is missing data-title");
    await page.locator("#session-filter").fill(title);
    await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe(title);

    await page.getByRole("tab", { name: "Rooms" }).click();

    await expect.poll(() => new URL(page.url()).searchParams.get("view")).toBe("rooms");
    expect(new URL(page.url()).searchParams.get("q")).toBe(title);
    // The swapped-in toolbar re-reads the mirror off the pushed URL.
    await expect(page.locator("#session-filter")).toHaveValue(title);
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

test.describe("Room filter", () => {
  const denseEventUrl = "/chronology/event/kapitularz-2025-anonymized/";

  test("groups the rooms under their parent space, in panel order", async ({ page }) => {
    await page.goto(denseEventUrl);
    await page.getByRole("button", { exact: true, name: "Filters" }).click();

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
    await page.getByRole("button", { exact: true, name: "Filters" }).click();

    const venue = await page
      .locator('#space-filter option[value^="venue:"]')
      .first()
      .getAttribute("value");
    if (!venue) throw new Error("location filter has no venue option");
    const venueId = venue.replace("venue:", "");
    const spacesOf = (selector: string) =>
      page
        .locator(selector)
        .evaluateAll((nodes) =>
          [...new Set(nodes.map((node) => (node as HTMLElement).dataset.space))].sort(),
        );
    const rooms = await spacesOf(`.session[data-venue="${venueId}"]`);
    expect(rooms.length).toBeGreaterThan(1);

    await page.locator("#space-filter").selectOption(venue);

    const visible = page.locator(".session-wrapper:not([hidden])");
    await expect.poll(() => visible.count()).toBeGreaterThan(0);
    for (const card of await visible.locator(".session").all())
      await expect(card).toHaveAttribute("data-venue", venueId);
    expect(await spacesOf(".session-wrapper:not([hidden]) .session")).toEqual(rooms);
  });

  test("narrows the list to the chosen room", async ({ page }) => {
    await page.goto(denseEventUrl);
    await page.getByRole("button", { exact: true, name: "Filters" }).click();

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
