import { type Locator, type Page } from "@playwright/test";

import { expect, test } from "./helpers/fixtures";

// Multi-day small event (card layout): Mega + Cozy on day one, Neon on day two.
const SMALL_EVENT_URL = "/event/autumn-open/";
const MEGA = "Mega Strategy Lab";
const COZY = "Cozy Storytellers Circle";
const NEON = "Przygoda w Mieście Neonów";
// Single-day small event: nothing to fold, so no toggle to offer.
const SINGLE_DAY_EVENT_URL = "/event/frostfire-con/";
// The dense seeded event: compact ledger by default, rooms grid on ?view=rooms.
const DENSE_EVENT_URL = "/event/kapitularz-2025-anonymized/";

const WEEKDAY = /^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b/;

const dayToggles = (page: Page) =>
  page.locator("[data-schedule-day]").getByRole("button", { name: WEEKDAY });

const card = (page: Page, title: string) =>
  page.getByRole("link", { name: `Open details for ${title}` });

const sessionLinks = (scope: Page | Locator) =>
  scope.getByRole("link", { name: /^Open details for / });

const squash = (text: string | null) => (text ?? "").replaceAll(/\s+/g, " ").trim();

// The session titles each day of the rooms grid holds, in reading order, keyed
// by the day headings that delimit them. Setup only — assertions go through
// roles and accessible names.
const roomTitlesByDay = async (page: Page): Promise<string[][]> =>
  page.locator(".room-lanes-body").evaluate((body) => {
    const days: string[][] = [];
    let current: string[] = [];
    for (const element of body.querySelectorAll("[data-day-heading], article")) {
      if (element.matches("article")) {
        current.push(
          (element.querySelector(".session-link")?.textContent ?? "")
            .replace(/\s+/g, " ")
            .trim()
            .replace(/^Open details for /, ""),
        );
      } else {
        current = [];
        days.push(current);
      }
    }
    return days;
  });

// An overnight session belongs to both sides of midnight, so its title shows
// up on two days; assertions about one day need a title the other lacks.
const onlyOn = (day: string[], other: string[]): string => {
  const title = day.find((candidate) => !other.includes(candidate));
  if (!title) throw new Error("The fixture needs a session unique to the day");
  return title;
};

test.describe("Folding days on the card schedule", () => {
  test("a day folds behind its heading and unfolds on demand", async ({ page }) => {
    await page.goto(SMALL_EVENT_URL);
    const days = dayToggles(page);
    await expect(days).toHaveCount(2);
    await expect(days.first()).toHaveAttribute("aria-expanded", "true");

    await expect(days.first()).toHaveAttribute("aria-controls", /^schedule-day-/);
    const controlled = (await days.first().getAttribute("aria-controls")) ?? "";

    await days.first().click();

    await expect(page.locator(`[id="${controlled}"]`)).toBeHidden();
    await expect(card(page, MEGA)).toBeHidden();
    await expect(card(page, COZY)).toBeHidden();
    await expect(card(page, NEON)).toBeVisible();
    await expect(days.first()).toHaveAttribute("aria-expanded", "false");
    // A fold is a reading gesture, not a filter: no chip shows up, nothing to
    // clear, and the address stays shareable as-is.
    await expect(page.getByRole("button", { name: "Remove filter" })).toHaveCount(0);
    expect(new URL(page.url()).search).toBe("");

    await days.first().click();
    await expect(card(page, MEGA)).toBeVisible();
    await expect(days.first()).toHaveAttribute("aria-expanded", "true");
  });

  test("a single-day schedule offers nothing to fold", async ({ page }) => {
    await page.goto(SINGLE_DAY_EVENT_URL);

    await expect(sessionLinks(page).first()).toBeVisible();
    await expect(dayToggles(page)).toHaveCount(0);
  });

  test("a finished day arrives folded", async ({ page }) => {
    await page.goto(SMALL_EVENT_URL);
    // Move the clock onto the event's second day; the first is then yesterday.
    const dayTwoStart = await page
      .locator("[data-schedule-day]")
      .nth(1)
      .locator(".session")
      .first()
      .getAttribute("data-start");
    if (!dayTwoStart) throw new Error("The fixture needs a session on day two");
    await page.clock.install({ time: new Date(Date.parse(dayTwoStart)) });
    await page.goto(SMALL_EVENT_URL);

    const days = dayToggles(page);
    await expect(days.first()).toHaveAttribute("aria-expanded", "false");
    await expect(card(page, MEGA)).toBeHidden();
    await expect(card(page, NEON)).toBeVisible();

    // Folded, not gone: yesterday's programme is one click away.
    await days.first().click();
    await expect(card(page, MEGA)).toBeVisible();
  });
});

test.describe("Folding days on the ledger", () => {
  test("a day folds behind its heading while the others read on", async ({ page }) => {
    await page.goto(DENSE_EVENT_URL);
    const [dayOne, dayTwo] = [
      page.locator("[data-schedule-day]").first(),
      page.locator("[data-schedule-day]").nth(1),
    ];
    const toggle = dayOne.getByRole("button", { name: WEEKDAY });
    await expect(sessionLinks(dayOne).first()).toBeVisible();

    await toggle.click();

    await expect(toggle).toBeVisible();
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(sessionLinks(dayOne).first()).toBeHidden();
    await expect(sessionLinks(dayTwo).first()).toBeVisible();

    await toggle.click();
    await expect(sessionLinks(dayOne).first()).toBeVisible();
  });

  test("jumping to an hour from the rail unfolds its day", async ({ page }) => {
    await page.goto(DENSE_EVENT_URL);
    const dayTwo = page.locator("[data-schedule-day]").nth(1);
    const toggle = dayTwo.getByRole("button", { name: WEEKDAY });
    await toggle.click();
    await expect(sessionLinks(dayTwo).first()).toBeHidden();

    const dayName = squash(await toggle.textContent()).split(" ")[0];
    await page
      .getByRole("link", { name: new RegExp(`^Jump to ${dayName}`) })
      .filter({ visible: true })
      .first()
      .click();

    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(sessionLinks(dayTwo).first()).toBeVisible();
  });

  test("a finished convention arrives fully unfolded", async ({ page }) => {
    await page.goto(DENSE_EVENT_URL);
    const lastEnd = await page
      .locator("[data-schedule-day]")
      .last()
      .locator(".session")
      .last()
      .getAttribute("data-end");
    if (!lastEnd) throw new Error("The fixture needs a session on the last day");
    await page.clock.install({ time: new Date(Date.parse(lastEnd) + 48 * 3600 * 1000) });
    await page.goto(DENSE_EVENT_URL);

    // Every day is over, so the reader came for the archive — nothing hides.
    for (const toggle of await dayToggles(page).all()) {
      await expect(toggle).toHaveAttribute("aria-expanded", "true");
    }
    await expect(sessionLinks(page.locator("[data-schedule-day]").first()).first()).toBeVisible();
  });

  test("finished days arrive folded", async ({ page }) => {
    await page.goto(DENSE_EVENT_URL);
    const dayTwoStart = await page
      .locator("[data-schedule-day]")
      .nth(1)
      .locator(".session")
      .first()
      .getAttribute("data-start");
    if (!dayTwoStart) throw new Error("The fixture needs a session on day two");
    await page.clock.install({ time: new Date(Date.parse(dayTwoStart)) });
    await page.goto(DENSE_EVENT_URL);

    const dayOne = page.locator("[data-schedule-day]").first();
    const toggle = dayOne.getByRole("button", { name: WEEKDAY });
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(sessionLinks(dayOne).first()).toBeHidden();
    await expect(sessionLinks(page.locator("[data-schedule-day]").nth(1)).first()).toBeVisible();

    await toggle.click();
    await expect(sessionLinks(dayOne).first()).toBeVisible();
  });
});

test.describe("Folding days on the rooms grid", () => {
  test("a day folds to its seam and unfolds from it", async ({ page }) => {
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);
    const titles = await roomTitlesByDay(page);
    expect(titles.length).toBeGreaterThan(1);
    const dayTwoTitle = onlyOn(titles[1], titles[0]);
    const dayOneTitle = onlyOn(titles[0], titles[1]);

    // The first in-grid seam heads day two; day one opens the grid seamlessly.
    const seamToggle = page
      .locator(".room-lanes-day")
      .first()
      .getByRole("button", { name: WEEKDAY });
    await seamToggle.click();

    await expect(seamToggle).toHaveAttribute("aria-expanded", "false");
    await expect(card(page, dayTwoTitle).first()).toBeHidden();
    await expect(card(page, dayOneTitle).first()).toBeVisible();

    await seamToggle.click();
    await expect(seamToggle).toHaveAttribute("aria-expanded", "true");
    await expect(card(page, dayTwoTitle).first()).toBeVisible();
  });

  test("the sticky day bar folds the day in view — the first day included", async ({ page }) => {
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);
    const titles = await roomTitlesByDay(page);
    const dayOneTitle = onlyOn(titles[0], titles[1]);
    const barToggle = page.locator(".room-lanes-day-current").getByRole("button");
    await expect(barToggle).toHaveAttribute("aria-expanded", "true");

    await barToggle.click();

    await expect(barToggle).toHaveAttribute("aria-expanded", "false");
    await expect(card(page, dayOneTitle).first()).toBeHidden();

    await barToggle.click();
    await expect(card(page, dayOneTitle).first()).toBeVisible();
  });

  test("a finished convention keeps every day open on the rooms grid", async ({ page }) => {
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);
    const titles = await roomTitlesByDay(page);
    const dayOneTitle = onlyOn(titles[0], titles[1]);
    const lastHourEnd = await page
      .locator(".room-lanes-line[data-row-end]")
      .last()
      .getAttribute("data-row-end");
    if (!lastHourEnd) throw new Error("The fixture needs hour rows");
    await page.clock.install({ time: new Date(Date.parse(lastHourEnd) + 48 * 3600 * 1000) });
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);

    await expect(card(page, dayOneTitle).first()).toBeVisible();
    const barToggle = page.locator(".room-lanes-day-current").getByRole("button");
    await expect(barToggle).toHaveAttribute("aria-expanded", "true");
  });

  test("finished days arrive folded and the bar brings them back", async ({ page }) => {
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);
    const titles = await roomTitlesByDay(page);
    const dayOneTitle = onlyOn(titles[0], titles[1]);
    const dayTwoTitle = onlyOn(titles[1], titles[0]);
    const dayTwoStart = await page
      .locator('.room-lanes-line[data-lane-day="1"]')
      .first()
      .getAttribute("data-row-start");
    if (!dayTwoStart) throw new Error("The fixture needs hour rows on day two");
    await page.clock.install({ time: new Date(Date.parse(dayTwoStart) + 30 * 60_000) });
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);

    await expect(card(page, dayOneTitle).first()).toBeHidden();
    await expect(card(page, dayTwoTitle).first()).toBeVisible();

    // At the top of the grid the bar names the folded first day and offers the
    // way back in.
    const barToggle = page.locator(".room-lanes-day-current").getByRole("button");
    await expect(barToggle).toHaveAttribute("aria-expanded", "false");
    await barToggle.click();
    await expect(card(page, dayOneTitle).first()).toBeVisible();
  });
});
