import { type Page } from "@playwright/test";
import path from "node:path";

import { expect, test } from "./helpers/fixtures";
import { DENSE_EVENT_URL } from "./helpers/urls";

const EVENT_URL = "/event/autumn-open/";
// The dense seeded event: the only one over the compact-schedule threshold,
// so the only one that offers a second layout to switch to.
const MEGA = "Mega Strategy Lab";
const NEON = "Przygoda w Mieście Neonów";
// Seeded with no participants limit: the drop-in the enrollment filter leaves out.
const COZY = "Cozy Storytellers Circle";

const card = (page: Page, title: string) =>
  page.getByRole("link", { name: `Open details for ${title}` });

// Set after load; a full navigation would wipe it, an htmx swap keeps it.
const markPage = (page: Page) =>
  page.evaluate(() => {
    (globalThis as unknown as { __sameDocument?: boolean }).__sameDocument = true;
  });

const stayedOnPage = (page: Page) =>
  page.evaluate(
    () => (globalThis as unknown as { __sameDocument?: boolean }).__sameDocument === true,
  );

const enrollmentOnly = (page: Page) => page.getByRole("checkbox", { name: "Only with enrollment" });

const squash = (text: string | null) => (text ?? "").replaceAll(/\s+/g, " ").trim();

const clockAfter = (clock: string, minutes: number) => {
  const [hour, minute] = clock.split(":").map(Number);
  const total = (hour * 60 + minute + minutes) % (24 * 60);
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
};

const scheduleMoment = (instant: string | null) => {
  const clock = /T(?<clock>\d\d:\d\d)/.exec(instant ?? "")?.groups?.clock;
  if (!instant || !clock) throw new Error(`Invalid schedule instant: ${instant}`);
  return { timestamp: Date.parse(instant), clock };
};

// The instant the programme opens. Setup only — nothing asserts on these.
const firstHour = async (page: Page) =>
  scheduleMoment(await page.locator("[data-row-start]").first().getAttribute("data-row-start"));

const firstStart = async (page: Page) =>
  scheduleMoment(
    await page
      .locator(".session-grid .session-wrapper .session")
      .first()
      .getAttribute("data-start"),
  );

const firstSessionEnd = async (page: Page) =>
  scheduleMoment(
    await page
      .locator(".session-grid .session-wrapper .session")
      .first()
      .getAttribute("data-session-end"),
  );

const finalSessionRange = async (page: Page) => {
  const sessions = page.locator(".session-grid .session-wrapper .session");
  const starts = scheduleMoment(await sessions.last().getAttribute("data-start"));
  const ends = await sessions.evaluateAll((elements) =>
    elements.map((element) => Date.parse((element as HTMLElement).dataset.end ?? "")),
  );
  return { starts, endsAt: Math.max(...ends) };
};

test.describe("Event schedule views", () => {
  test("the view switcher offers nothing when the schedule has one layout", async ({ page }) => {
    await page.goto(EVENT_URL);

    await expect(page.getByRole("tablist", { name: "Schedule view" })).toHaveCount(0);
  });

  test("the rooms tab swaps the layout in without leaving the page", async ({ page }) => {
    await page.goto(DENSE_EVENT_URL);
    await markPage(page);

    await page.getByRole("tab", { name: "Rooms" }).click();

    // The dense event's rooms layout is the suite's slowest render; under a
    // parallel run the boosted GET outlasts the default expect timeout.
    await expect(page.locator(".room-lanes").first()).toBeVisible({ timeout: 30_000 });
    await expect(page).toHaveURL(/\?view=rooms$/);
    expect(await stayedOnPage(page)).toBe(true);
  });

  test("sessions that touch off the hour stack instead of splitting the column", async ({
    page,
  }) => {
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);

    // Seeded back to back at :30 (kapitularz_print_seed.py). Everything else in
    // the programme starts on the hour, so this pair is the only thing that
    // cuts a row.
    const handovers = page.getByRole("link", { name: /Open details for Half-hour handover/ });
    await expect(handovers).toHaveCount(2);
    const boxes = await Promise.all([
      handovers.nth(0).boundingBox(),
      handovers.nth(1).boundingBox(),
    ]);
    const [first, second] = boxes;
    if (!first || !second) throw new Error("The fixture needs both handover tiles laid out");

    // Each keeps the whole room column and they stack. Side by side at half
    // width is how the grid draws two sessions running at once — which is what
    // a reader saw here while the rows were whole hours and these two shared
    // one.
    expect(Math.abs(first.x - second.x)).toBeLessThan(1);
    expect(Math.abs(first.width - second.width)).toBeLessThan(1);
    const [above, below] = first.y <= second.y ? [first, second] : [second, first];
    expect(above.y + above.height).toBeLessThanOrEqual(below.y + 1);

    // The axis stays an hour ruler: the boundary those two share is ruled, but
    // only whole hours are named. A bare time on screen is the ruler — a tile
    // prints its own as a range, and the hour filter's matching options are
    // inside a closed select.
    const onAxis = (time: string) =>
      page.getByText(time, { exact: true }).filter({ visible: true });
    await expect(onAxis("16:00").first()).toBeVisible();
    await expect(onAxis("16:30")).toHaveCount(0);
  });

  test("the hour scrubber can still reach an hour whose session starts at :30", async ({
    page,
  }) => {
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);

    // Nothing else in the programme starts in the handovers' first hour
    // (kapitularz_print_seed.py), so that hour is reachable only through a
    // session starting at :30. A grid keying its anchors on the cut rather than
    // the hour strands that marker: it has nothing to scroll to, and the rail
    // hides it on first paint.
    const markers = page.getByRole("link", { name: /^Jump to / });
    await expect(markers.first()).toBeAttached();
    const hrefs = await markers.evaluateAll((links) =>
      links.map((link) => link.getAttribute("href") ?? ""),
    );
    const unreachable = await page.evaluate(
      (targets) => targets.filter((target) => document.querySelector(target) === null),
      hrefs,
    );
    expect(unreachable).toEqual([]);
  });

  test("a session through the day turnover is one tile across the seam", async ({ page }) => {
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);

    // Seeded to run 22:00 to 07:00 (kapitularz_print_seed.py): days turn over
    // at 06:00, so the ledger lists it under both days, but the grid's axis
    // runs straight through the seam and draws it once, with its real times.
    const time = page.getByText("22:00–07:00", { exact: true });
    await expect(time).toHaveCount(1);
    const tile = await time.evaluate((el) => {
      const cell = el.closest<HTMLElement>(".room-lanes-cell");
      const session = el.closest<HTMLElement>(".session");
      return {
        id: session?.dataset.sessionId ?? "",
        row: Number(cell?.dataset.tileRow),
        span: Number(cell?.dataset.tileSpan),
      };
    });
    await expect(
      page.getByRole("link", { name: /Open details for/ }).filter({
        has: page.locator(`xpath=ancestor::*[@data-session-id="${tile.id}"]`),
      }),
    ).toHaveCount(1);

    // A day heading sits inside the tile's rows, and its band is drawn over
    // the tile rather than hidden behind it.
    const seams = await page.getByRole("heading", { level: 3 }).evaluateAll((headings) =>
      headings.flatMap((heading) => {
        const seam = heading.closest<HTMLElement>(".room-lanes-day");
        return seam
          ? [{ row: Number(seam.dataset.laneRow), zIndex: Number(getComputedStyle(seam).zIndex) }]
          : [];
      }),
    );
    const crossed = seams.filter((seam) => seam.row > tile.row && seam.row < tile.row + tile.span);
    expect(crossed).toHaveLength(1);
    expect(crossed[0]?.zIndex ?? 0).toBeGreaterThan(10);
  });

  test("hours of lull fold into one thin labelled row", async ({ page }) => {
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);

    // The overnight session runs 22:00 to 07:00 and the next programme opens
    // at 10:00, so there are two lulls long enough to fold: the night under
    // the running session, and the morning after it ends.
    await expect(page.getByText(/Nothing new until/)).toHaveText([
      "Nothing new until 06:00",
      "Nothing new until 10:00",
    ]);
    const label = page.getByText("Nothing new until 10:00");
    const fold = await label.evaluate((el) => {
      const line = el.closest<HTMLElement>(".room-lanes-line");
      // The row after the fold is the 10:00 hour the label names.
      const next = document.querySelector<HTMLElement>(
        `.room-lanes-line[data-lane-row="${Number(line?.dataset.laneRow) + 1}"]`,
      );
      return {
        start: Date.parse(line?.dataset.rowStart ?? ""),
        end: Date.parse(line?.dataset.rowEnd ?? ""),
        height: line?.getBoundingClientRect().height ?? 0,
        anchorsSlot: line?.querySelector(".time-slot-section") !== null,
        nextStart: Date.parse(next?.dataset.rowStart ?? ""),
        nextHeight: next?.getBoundingClientRect().height ?? 0,
      };
    });
    expect(fold.end - fold.start).toBe(3 * 60 * 60 * 1000);
    expect(fold.nextStart).toBe(fold.end);
    // Nothing starts in a fold, so the scrubber has no target there.
    expect(fold.anchorsSlot).toBe(false);
    // Thinner than an hour: the fold stands in for hours nobody programmed.
    expect(fold.nextHeight).toBeGreaterThan(0);
    expect(fold.height).toBeLessThan(fold.nextHeight);
  });

  test("the grid offers a sideways scrollbar at its bottom edge", async ({ page }) => {
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);
    const foot = page.locator("[data-room-lanes-foot]").first();
    const body = page.locator("[data-room-lanes-scroll]").first();

    // A real scroller — that is what puts a scrollbar under the grid for mouse
    // users. The body's own yields to it, because the foot pins to the
    // viewport while the body's would surface only at the grid's end.
    await expect(foot).toHaveCSS("overflow-x", "auto");
    await expect(body).toHaveCSS("scrollbar-width", "none");

    // Targets derived from the actual overflow, so a shrunken fixture fails
    // on this precondition instead of an opaque clamped-scroll poll timeout.
    const max = await foot.evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(max).toBeGreaterThanOrEqual(300);
    const far = Math.floor(max / 2);

    // Dragging the handle pans the grid, and the grid drags the handle along.
    await foot.evaluate((el, left) => {
      el.scrollLeft = left;
    }, far);
    await expect.poll(() => body.evaluate((el) => el.scrollLeft)).toBe(far);

    await body.evaluate((el) => {
      el.scrollLeft = 0;
    });
    await expect.poll(() => foot.evaluate((el) => el.scrollLeft)).toBe(0);
  });

  test("the grid is reachable by keyboard to pan it", async ({ page }) => {
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);
    // A scroll container earns a tab stop by itself only while nothing inside
    // it is focusable — tiles are — and only in some engines, so the grid names
    // itself and takes one, rather than leaving a keyboard user to tab through
    // every tile to travel sideways.
    const grid = page.getByRole("region", { name: "Rooms schedule" });

    // Reached by Tab, not by focus(): focus() succeeds on tabindex="-1" too,
    // and a focused scroller pans on arrow keys whatever its tabindex says, so
    // asserting focusability would pass on exactly the grid this test exists to
    // rule out — one no keyboard user can get to. Tabbing from the top of the
    // page is the user's own route, and it is the browser's model of the tab
    // order rather than a guess at it: predicting the previous stop from the
    // DOM misses that a fixed or hidden control is skipped.
    await page.evaluate(() => {
      document.body.focus();
    });
    let reached = false;
    for (let press = 0; press < 60 && !reached; press++) {
      await page.keyboard.press("Tab");
      reached = await grid.evaluate((el) => el === document.activeElement);
    }
    expect(reached).toBe(true);

    const panned = async () => grid.evaluate((el) => Math.round(el.scrollLeft));
    expect(await panned()).toBe(0);
    await page.keyboard.press("ArrowRight");
    await expect.poll(panned).toBeGreaterThan(0);
  });

  test("the current day stays outside the edge fade and follows vertical scroll", async ({
    page,
  }) => {
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);
    const currentDayDisplay = page.locator(".room-lanes-day-current");
    const currentDay = currentDayDisplay.locator("[data-room-lanes-day-current]");
    // The bar doubles as the shown day's fold toggle (see the folding spec).
    await expect(currentDay).toHaveRole("button");
    // Every day is a heading. The first opens the grid and has no seam to
    // scroll past — it is the one the header starts on — so the day to scroll
    // into is the second.
    const days = page.getByRole("heading", { level: 3 });
    expect(await days.count()).toBeGreaterThan(1);
    const [first, second] = (await days.allTextContents()).map(squash);
    expect(squash(await currentDay.textContent())).toContain(first);
    expect(squash(await currentDay.textContent())).not.toContain(second);
    expect(
      await currentDay.evaluate((label) => label.closest("[data-room-lanes-head]") === null),
    ).toBe(true);

    // To the top of the scroller, not merely into view: the header floats over
    // the grid, and a seam parked just below the fold is still under it.
    await days.nth(1).evaluate((el) => {
      el.scrollIntoView({ block: "start" });
    });
    await expect.poll(async () => squash(await currentDay.textContent())).toContain(second);
  });

  test("day seams bypass the fade while cards keep the body mask", async ({ page }) => {
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);
    const body = page.locator("[data-room-lanes-scroll]").first();
    const days = page.getByRole("heading", { level: 3 });
    const mirrors = page.locator("[data-room-lanes-overlays] h3");

    expect(await days.count()).toBeGreaterThan(1);
    await expect(mirrors).toHaveCount((await days.count()) - 1);
    expect(await body.evaluate((el) => getComputedStyle(el).maskImage)).not.toBe("none");

    // The mask above is only half the claim: it says a gradient is installed,
    // not that it tracks the grid. Both halves run their fades off the body's
    // scroll timeline, so both edges have to darken as the columns reach them —
    // the strip especially, since a strip fading on a timeline of its own is
    // what left one crisp edge above a permanently faded one. Engines without
    // scroll timelines never fade — there the @property initial value is the
    // whole behaviour — so the check is skipped rather than inverted.
    const head = page.locator("[data-room-lanes-head]").first();
    const faded = async (half: typeof body) =>
      half.evaluate((el) => Number(getComputedStyle(el).getPropertyValue("--fade-end-opacity")));
    if (await page.evaluate(() => CSS.supports("timeline-scope: --room-lanes-x"))) {
      expect(await faded(body)).toBeLessThan(1);
      expect(await faded(head)).toBeLessThan(1);
      await body.evaluate((el) => {
        el.scrollLeft = el.scrollWidth - el.clientWidth;
      });
      await expect.poll(() => faded(body)).toBe(1);
      await expect.poll(() => faded(head)).toBe(1);
      await body.evaluate((el) => {
        el.scrollLeft = 0;
      });
    }

    const source = days.nth(1);
    const mirror = mirrors.first();
    await expect(mirror).toHaveText((await source.textContent()) ?? "");
    expect(
      await mirror.evaluate((label) => label.closest("[data-room-lanes-scroll]") === null),
    ).toBe(true);

    const [sourceBox, mirrorBox] = await Promise.all([source.boundingBox(), mirror.boundingBox()]);
    expect(sourceBox).not.toBeNull();
    expect(mirrorBox).not.toBeNull();
    expect(Math.abs((sourceBox?.y ?? 0) - (mirrorBox?.y ?? 0))).toBeLessThan(1);
  });

  test("day headings delimit their sessions in reading order", async ({ page }) => {
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);

    const order = await page
      .locator(".room-lanes-body")
      .evaluate((body) =>
        [...body.querySelectorAll("[data-day-heading], article")].map((element) =>
          element.matches("article") ? "session" : "day",
        ),
      );
    const secondDay = order.indexOf("day", 1);
    expect(order[0]).toBe("day");
    expect(secondDay).toBeGreaterThan(1);
    expect(order.slice(1, secondDay)).toContain("session");
    expect(order.slice(secondDay + 1)).toContain("session");
  });

  test("room tiles read left to right and expose their room", async ({ page }) => {
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);

    const cells = page.locator(".room-lanes-cell");
    const colsByRow = await cells.evaluateAll((elements) => {
      const rows: Record<string, number[]> = {};
      for (const element of elements) {
        const row = (element as HTMLElement).dataset.tileRow ?? "";
        (rows[row] ??= []).push(Number((element as HTMLElement).dataset.tileCol));
      }
      return rows;
    });
    for (const cols of Object.values(colsByRow)) {
      expect(cols).toEqual([...cols].sort((left, right) => left - right));
    }

    const links = cells.locator(".session-link");
    const associations = await links.evaluateAll((elements) =>
      elements.map((element) => {
        const target = document.getElementById(element.getAttribute("aria-describedby") ?? "");
        return (target?.textContent ?? "").replace(/\s+/g, " ").trim();
      }),
    );
    expect(associations.length).toBeGreaterThan(0);
    expect(associations.every(Boolean)).toBe(true);
    await expect(links.first()).toHaveAccessibleDescription(associations[0]);
  });

  test("same-room conflicts remain visible and repack after filtering", async ({ page }) => {
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);

    const cells = page.locator(".room-lanes-cell");
    const first = cells.first();
    const second = cells.nth(1);
    await expect(first).toBeVisible();
    await expect(second).toBeVisible();
    await second.evaluate(
      (cell, placement) => {
        const element = cell as HTMLElement;
        element.dataset.tileCol = placement.col;
        element.dataset.tileRow = placement.row;
        element.dataset.tileSpan = placement.span;
      },
      {
        col: (await first.getAttribute("data-tile-col")) ?? "",
        row: (await first.getAttribute("data-tile-row")) ?? "",
        span: (await first.getAttribute("data-tile-span")) ?? "",
      },
    );

    await first.locator(".session").evaluate((session) => {
      const element = session as HTMLElement;
      element.dataset.start = "2026-07-10T10:45:00+02:00";
      element.dataset.end = "2026-07-10T10:55:00+02:00";
    });
    await second.locator(".session").evaluate((session) => {
      const element = session as HTMLElement;
      element.dataset.start = "2026-07-10T10:05:00+02:00";
      element.dataset.end = "2026-07-10T10:15:00+02:00";
      document.dispatchEvent(new CustomEvent("schedule:filtered"));
    });

    const [firstBox, secondBox] = await Promise.all([first.boundingBox(), second.boundingBox()]);
    expect(firstBox).not.toBeNull();
    expect(secondBox).not.toBeNull();
    expect((secondBox?.x ?? 0) + (secondBox?.width ?? 0)).toBeLessThanOrEqual(
      (firstBox?.x ?? 0) + 1,
    );
    for (const cell of [first, second]) {
      expect(
        await cell.evaluate((element) => {
          const box = element.getBoundingClientRect();
          const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
          return hit !== null && element.contains(hit);
        }),
      ).toBe(true);
    }

    const conflictWidth = firstBox?.width ?? 0;
    await second.locator(".session-wrapper").evaluate((session) => {
      (session as HTMLElement).hidden = true;
      document.dispatchEvent(new CustomEvent("schedule:filtered"));
    });
    await expect(second).toBeHidden();
    await expect
      .poll(async () => (await first.boundingBox())?.width ?? 0)
      .toBeGreaterThan(conflictWidth * 1.8);
    await expect(first.locator(".session-link")).toBeVisible();
  });

  test("a line marks where the programme has got to", async ({ page }) => {
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);
    // Arrangement, not assertion: the seeded event sits months from the real
    // date, so the clock has to be moved onto its programme before a reader
    // could ever see the line.
    const opens = await firstHour(page);
    const half = new Date(opens.timestamp + 30 * 60_000);
    const halfClock = clockAfter(opens.clock, 30);
    await page.clock.install({ time: half });
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);

    const roomMarker = page.locator("[data-room-lanes-now]");
    const marker = roomMarker.locator(".schedule-now-pill");
    await expect(roomMarker).toHaveAttribute("aria-hidden", "true");
    await expect(marker).toContainText(halfClock);
    await expect(marker).toBeVisible();
    expect(
      await marker.evaluate((label) => label.closest("[data-room-lanes-scroll]") === null),
    ).toBe(true);

    // It sits between the hour it belongs to and the next one on the axis.
    const between = await Promise.all(
      [opens.clock, clockAfter(opens.clock, 60)].map((hour) =>
        page.getByText(hour, { exact: true }).filter({ visible: true }).first().boundingBox(),
      ),
    );
    const line = await marker.boundingBox();
    const rule = await page.locator(".room-lanes-now .schedule-now-line").boundingBox();
    expect(line).not.toBeNull();
    expect(rule).not.toBeNull();
    expect(Math.abs((line?.y ?? 0) + (line?.height ?? 0) / 2 - (rule?.y ?? 0))).toBeLessThan(1.5);
    expect(line?.y).toBeGreaterThan(between[0]?.y ?? 0);
    expect(line?.y).toBeLessThan(between[1]?.y ?? 0);

    await page.clock.runFor(60_000);
    await expect(marker).toContainText(clockAfter(opens.clock, 31));
    await expect
      .poll(
        async () =>
          (await page.locator(".room-lanes-now .schedule-now-line").boundingBox())?.y ?? 0,
      )
      .toBeGreaterThan(rule?.y ?? 0);

    // A day before the doors open, nothing on the grid is now. The clock
    // ticking is what has to notice, not a reload.
    await page.clock.setFixedTime(new Date(opens.timestamp - 24 * 3600 * 1000));
    await page.clock.runFor(60_000);
    await expect(marker).toBeHidden();
  });

  test("a spanning session keeps the current-hour geometry after filtering", async ({ page }) => {
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);

    const lines = page.locator(".room-lanes-line");
    const sourceLine = lines.first();
    const targetLine = lines.nth(1);
    const sourceRow = (await sourceLine.getAttribute("data-lane-row")) ?? "";
    const targetRow = (await targetLine.getAttribute("data-lane-row")) ?? "";
    await expect(targetLine.locator(".time-slot-section")).toHaveCount(1);
    const targetStart = await targetLine.getAttribute("data-row-start");
    const targetEnd = await targetLine.getAttribute("data-row-end");
    if (!sourceRow || !targetRow || !targetStart || !targetEnd) {
      throw new Error("The fixture needs two consecutive room rows");
    }

    const at = (Date.parse(targetStart) + Date.parse(targetEnd)) / 2;
    await page.clock.install({ time: new Date(at) });
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);

    const cells = page.locator(".room-lanes-cell");
    await cells.evaluateAll(
      (elements, placement) => {
        for (const element of elements) {
          const session = element.querySelector<HTMLElement>(".session-wrapper");
          if (session) session.hidden = true;
        }
        const spanning = elements[0] as HTMLElement | undefined;
        const session = spanning?.querySelector<HTMLElement>(".session-wrapper");
        if (!spanning || !session) throw new Error("The fixture needs a room tile");
        spanning.dataset.tileRow = placement.sourceRow;
        spanning.dataset.tileSpan = "2";
        spanning.style.gridRowEnd = "span 2";
        session.hidden = false;

        const target = document.querySelector<HTMLElement>(
          `.room-lanes-line[data-lane-row="${placement.targetRow}"]`,
        );
        const sentinel = target?.querySelector<HTMLElement>(".time-slot-section");
        if (sentinel) sentinel.hidden = true;
        const marker = document.querySelector<HTMLElement>("[data-room-lanes-now]");
        if (marker) marker.hidden = true;
      },
      { sourceRow, targetRow },
    );

    await page.evaluate(() => document.dispatchEvent(new CustomEvent("schedule:filtered")));
    await page.clock.runFor(1);
    const matchingRows = await lines.evaluateAll(
      (elements, now) =>
        elements
          .filter((element) => {
            const row = element as HTMLElement;
            return (
              now >= Date.parse(row.dataset.rowStart ?? "") &&
              now < Date.parse(row.dataset.rowEnd ?? "")
            );
          })
          .map((element) => (element as HTMLElement).dataset.laneRow),
      at,
    );
    expect(matchingRows).toEqual([targetRow]);

    await expect(targetLine).toBeVisible();
    await expect(targetLine.locator(".time-slot-section")).toBeHidden();
    await expect(page.locator("[data-room-lanes-now] .schedule-now-pill")).toBeVisible();
    const [lineBox, markerBox] = await Promise.all([
      targetLine.boundingBox(),
      page.locator(".room-lanes-now .schedule-now-line").boundingBox(),
    ]);
    expect(lineBox).not.toBeNull();
    expect(markerBox).not.toBeNull();
    expect(markerBox?.y ?? 0).toBeGreaterThanOrEqual(lineBox?.y ?? 0);
    expect(markerBox?.y ?? 0).toBeLessThan((lineBox?.y ?? 0) + (lineBox?.height ?? 0));
  });

  test("the rooms grid dims a tile once the clock passes its end", async ({ page }) => {
    // The ledger row and the lane tile carry the same dimming rule written
    // twice, one per layout, so the grid needs its own witness.
    const tiles = page.locator(".room-lanes-cell .session");
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);
    const ends = scheduleMoment(await tiles.first().getAttribute("data-session-end"));
    await page.clock.install({ time: new Date(ends.timestamp - 60_000) });
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);

    await expect(tiles.first()).not.toHaveAttribute("data-ended");

    await page.clock.runFor(120_000);

    await expect(tiles.first()).toHaveAttribute("data-ended", "");
    await expect(tiles.first()).toHaveCSS("opacity", "0.65");
  });

  test("the search box takes a tap while a session modal is still animating out", async ({
    browserName,
    page,
  }) => {
    test.skip(browserName !== "chromium", "Slows animations over the devtools protocol");
    await page.goto(DENSE_EVENT_URL);
    await page
      .getByRole("link", { name: /^Open details for / })
      .first()
      .press("Enter");
    const dialog = page.locator("dialog.modal[open]");
    await expect(dialog).toBeVisible();

    const search = page.locator("#session-filter");
    const box = await search.boundingBox();
    if (!box) throw new Error("The search box needs a position to tap");
    // Held open for seconds, so the tap below lands mid-animation rather than
    // racing a quarter-second exit; a real reader's tap lands there too. A
    // playback rate, not an injected stylesheet: the page's CSP drops the
    // latter without a word.
    const devtools = await page.context().newCDPSession(page);
    await devtools.send("Animation.enable");
    await devtools.send("Animation.setPlaybackRate", { playbackRate: 0.05 });
    await page.keyboard.press("Escape");
    // The dialog closes inside the transition's update step, a frame in; from
    // then on the page is what the reader is tapping, whatever is still
    // animating above it. A raw pointer press, not click(): click() waits
    // until the element can receive pointer events, which is exactly the
    // wait a reader does not get.
    await expect(dialog).toHaveCount(0);
    // The animations start on the transition's ready step, a frame after the
    // close; wait for them so the tap is provably mid-animation.
    await page.waitForFunction(() =>
      document
        .getAnimations()
        .some((a) =>
          (a.effect as KeyframeEffect | null)?.pseudoElement?.startsWith("::view-transition"),
        ),
    );
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    await expect(search).toBeFocused();
  });

  test("the ledger stays unmarked before the programme opens", async ({ page }) => {
    await page.goto(DENSE_EVENT_URL);
    const opens = await firstStart(page);
    await page.clock.install({ time: new Date(opens.timestamp - 60_000) });
    await page.goto(DENSE_EVENT_URL);

    await expect(page.locator("[data-schedule-now]")).toBeHidden();
  });

  test("the ledger opens the current day at its top on a morning before its programme", async ({
    page,
  }) => {
    await page.goto(DENSE_EVENT_URL);
    // Three hours before day two's first session: yesterday is over, today has
    // not begun, and the seam belongs to today rather than to yesterday's tail.
    const secondDay = page.locator("[data-schedule-day]").nth(1);
    const opens = scheduleMoment(
      await secondDay.locator(".session-grid .session").first().getAttribute("data-start"),
    );
    const at = new Date(opens.timestamp - 3 * 60 * 60_000);
    const atClock = clockAfter(opens.clock, -3 * 60);
    await page.clock.install({ time: at });
    await page.goto(DENSE_EVENT_URL);

    const marker = page.getByText(`Now ${atClock}`);
    await expect(marker).toBeVisible();
    await expect(secondDay).not.toHaveAttribute("data-folded");
    const seamDay = await marker.evaluate(
      (el) => el.closest<HTMLElement>("[data-schedule-day]")?.dataset.day,
    );
    expect(seamDay).toBe(await secondDay.getAttribute("data-day"));
    const [line, heading, firstRow] = await Promise.all([
      marker.boundingBox(),
      secondDay.getByRole("heading").first().boundingBox(),
      secondDay.getByRole("article").first().boundingBox(),
    ]);
    const seamY = (line?.y ?? 0) + (line?.height ?? 0) / 2;
    expect(seamY).toBeGreaterThan((heading?.y ?? 0) + (heading?.height ?? 0));
    expect(seamY).toBeLessThanOrEqual((firstRow?.y ?? 0) + 1);
  });

  test("the ledger marks the seam between finished and upcoming", async ({ page }) => {
    await page.goto(DENSE_EVENT_URL);
    const opens = await firstStart(page);
    const at = new Date(opens.timestamp + 90 * 60_000);
    const atClock = clockAfter(opens.clock, 90);
    await page.clock.install({ time: at });
    await page.goto(DENSE_EVENT_URL);

    const marker = page.getByText(`Now ${atClock}`);
    await expect(marker).toBeVisible();

    // The row directly above the seam has started and the one directly below
    // has not — the only thing the seam claims. Read off the times the rows
    // print, which also checks the instant the clock was set from against what
    // the page actually shows.
    const line = await marker.boundingBox();
    const rows = await page.getByRole("article").evaluateAll((cards) =>
      cards.map((card) => ({
        hourY: card.closest(".time-slot-section")?.getBoundingClientRect().y ?? 0,
        text: (card as HTMLElement).innerText,
        y: card.getBoundingClientRect().y,
      })),
    );
    const startsAt = (text: string) => /\b(\d\d:\d\d)\b/.exec(text)?.[1] ?? "";
    const above = rows.filter((row) => row.y < (line?.y ?? 0)).at(-1);
    const below = rows.find((row) => row.y > (line?.y ?? 0));
    expect(above).toBeDefined();
    expect(below).toBeDefined();
    expect(startsAt(above?.text ?? "").localeCompare(atClock)).toBeLessThanOrEqual(0);
    expect(startsAt(below?.text ?? "").localeCompare(atClock)).toBeGreaterThan(0);
    expect(line?.y).toBeLessThan(below?.hourY ?? 0);
  });

  test("the ledger marker stays before tomorrow for an overnight session", async ({ page }) => {
    await page.goto(DENSE_EVENT_URL);
    await page.clock.install({ time: new Date("2026-07-10T21:30:00Z") });
    await page.goto(DENSE_EVENT_URL);

    await page.locator("[data-schedule-day]").evaluateAll((days) => {
      const current = days[0]?.querySelector<HTMLElement>(".session");
      const tomorrow = days[1]?.querySelector<HTMLElement>(".session");
      if (!current || !tomorrow) throw new Error("The fixture needs sessions on two days");
      for (const row of document.querySelectorAll<HTMLElement>(".session-wrapper")) {
        row.hidden = !row.contains(current) && !row.contains(tomorrow);
      }
      current.dataset.start = "2026-07-10T22:00:00+02:00";
      current.dataset.end = "2026-07-11T00:00:00+02:00";
      tomorrow.dataset.start = "2026-07-11T00:00:00+02:00";
      tomorrow.dataset.end = "2026-07-11T02:00:00+02:00";
      document.dispatchEvent(new CustomEvent("schedule:filtered"));
    });

    const marker = page.getByText("Now 23:30");
    await expect(marker).toBeVisible();
    const [line, tomorrow] = await Promise.all([
      marker.boundingBox(),
      page.locator("[data-schedule-day]").nth(1).getByRole("heading").first().boundingBox(),
    ]);
    expect(line).not.toBeNull();
    expect(tomorrow).not.toBeNull();
    expect(line?.y).toBeLessThan(tomorrow?.y ?? 0);
  });

  test("the ledger dims a session once the clock passes its end", async ({ page }) => {
    // The page outlives the reading it was served with: a phone left open on
    // the schedule keeps showing every session as still to come.
    await page.goto(DENSE_EVENT_URL);
    const ends = await firstSessionEnd(page);
    await page.clock.install({ time: new Date(ends.timestamp - 60_000) });
    await page.goto(DENSE_EVENT_URL);

    const row = page.locator(".session-grid .session-wrapper .session").first();
    await expect(row).not.toHaveAttribute("data-ended");

    await page.clock.runFor(120_000);

    await expect(row).toHaveAttribute("data-ended", "");
    await expect(row).toHaveCSS("opacity", "0.65");
    await expect(row).toHaveAttribute("data-status", "ended");
  });

  test("the ledger clock follows the event timezone across DST", async ({ page }) => {
    await page.goto(DENSE_EVENT_URL);
    await page.clock.install({ time: new Date("2026-03-29T01:30:00Z") });
    await page.goto(DENSE_EVENT_URL);

    await page.locator(".session-grid .session").evaluateAll((sessions) => {
      const [current, ...rest] = sessions as HTMLElement[];
      current.dataset.start = "2026-03-28T23:00:00+01:00";
      current.dataset.end = "2026-03-29T04:00:00+02:00";
      for (const session of rest) {
        const row = session.closest<HTMLElement>(".session-wrapper");
        if (row) row.hidden = true;
      }
      document.dispatchEvent(new CustomEvent("schedule:filtered"));
    });

    await expect(page.getByText("Now 03:30")).toBeVisible();
  });

  test("the ledger stays marked while the final sessions are running", async ({ page }) => {
    await page.goto(DENSE_EVENT_URL);
    const { starts, endsAt } = await finalSessionRange(page);
    const oneMinuteAfterStart = starts.timestamp + 60_000;
    expect(oneMinuteAfterStart).toBeLessThan(endsAt);
    await page.clock.install({ time: new Date(oneMinuteAfterStart) });
    await page.goto(DENSE_EVENT_URL);

    const marker = page.getByText(`Now ${clockAfter(starts.clock, 1)}`);
    await expect(marker).toBeVisible();
    const [line, finalRow] = await Promise.all([
      marker.boundingBox(),
      page.getByRole("article").last().boundingBox(),
    ]);
    expect(line).not.toBeNull();
    expect(finalRow).not.toBeNull();
    // The pill is centred on the seam line, so its midline is where the line is.
    const seamY = (line?.y ?? 0) + (line?.height ?? 0) / 2;
    expect(seamY).toBeGreaterThan((finalRow?.y ?? 0) + (finalRow?.height ?? 0) - 2);

    await page.clock.setFixedTime(new Date(endsAt + 60_000));
    await page.clock.runFor(60_000);
    await expect(marker).toBeHidden();
  });

  test("an empty Rooms filter hides the complete schedule chrome", async ({ page }) => {
    await page.goto(`${DENSE_EVENT_URL}?view=rooms&q=no-such-session`);

    await expect(page.getByText("No sessions match your filters")).toBeVisible();
    const lanes = page.locator(".room-lanes");
    await expect(lanes).toBeHidden();

    await page.getByRole("button", { name: "Clear all filters" }).click();
    await expect(page.getByText("No sessions match your filters")).toBeHidden();
    await expect(lanes).toBeVisible();
  });

  test("a filter that empties a day keeps its name and drops its hours", async ({ page }) => {
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);
    const lanes = page.locator(".room-lanes").first();
    const days = page.getByRole("heading", { level: 3 });
    const shownDays = await days.filter({ visible: true }).count();
    expect(shownDays).toBeGreaterThan(1);
    const rowSelector = ".room-lanes-time[data-lane-row]:not(.room-lanes-collapsed)";
    const rowCount = await lanes.locator(rowSelector).count();

    // One session's title from the last day: every earlier day empties out.
    const title = await page
      .getByRole("link", { name: /^Open details for / })
      .last()
      .textContent();
    await page
      .getByRole("textbox", { name: "Search by name or text..." })
      .fill((title ?? "").replace("Open details for ", "").trim());
    await expect.poll(() => lanes.locator(rowSelector).count()).toBeLessThan(rowCount);

    // The day names are the reader's map of the event, so none goes with its
    // rows — an emptied day stands as its heading alone, like a folded one.
    await expect(days.filter({ visible: true })).toHaveCount(shownDays);
    // A lull's label goes with its row: a collapsed fold must not paint its
    // label over whatever row comes next, doubling it with the neighbour's.
    const folds = lanes.locator(".room-lanes-line[data-row-track='fold']");
    await expect(folds.locator(":scope.room-lanes-collapsed")).not.toHaveCount(0);
    for (const fold of await folds.locator(":scope.room-lanes-collapsed").all()) {
      await expect(fold.locator(".room-lanes-fold-label")).toBeHidden();
    }
  });

  test("the grid pans like a map: drag the background, or anything with Space", async ({
    browserName,
    page,
  }) => {
    test.skip(
      browserName === "firefox",
      "Playwright's Firefox driver dispatches no pointerup/mouseup after a drag, so the pan never ends under automation (real Firefox fires mouseup)",
    );

    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);
    const body = page.locator("[data-room-lanes-scroll]").first();
    await body.scrollIntoViewIfNeeded();
    // The pan will move the page up, so give it explicit headroom — on a tall
    // viewport scrollIntoViewIfNeeded alone can leave the page at 0, where
    // the vertical assertion could never pass. Scrolled before the spot scan
    // below, whose coordinates are viewport-relative.
    await page.evaluate(() => {
      const app = document.querySelector(".app-scroll");
      if (app) app.scrollTop += 200;
    });

    // A background spot inside the viewport: on the grid, not on a tile link.
    const spot = await body.evaluate((el) => {
      const rect = el.getBoundingClientRect();
      const bottom = Math.min(rect.bottom, window.innerHeight);
      for (let y = bottom - 24; y > rect.top; y -= 48) {
        for (let x = rect.left + 80; x < rect.right - 24; x += 64) {
          if (!document.elementFromPoint(x, y)?.closest("a, button")) return { x, y };
        }
      }
      return null;
    });
    expect(spot).not.toBeNull();
    if (!spot) return;

    const appTop = () => page.evaluate(() => document.querySelector(".app-scroll")?.scrollTop ?? 0);
    const topBefore = await appTop();
    expect(topBefore).toBeGreaterThan(0);
    await page.mouse.move(spot.x, spot.y);
    await page.mouse.down();
    await page.mouse.move(spot.x - 180, spot.y + 60, { steps: 6 });
    await expect(body).toHaveClass(/room-lanes-panning/);
    await page.mouse.up();
    await expect(body).not.toHaveClass(/room-lanes-panning/);
    await expect.poll(() => body.evaluate((el) => el.scrollLeft)).toBeGreaterThanOrEqual(150);
    expect(await appTop()).toBeLessThan(topBefore);

    // Space turns even a session tile into a map handle, and the pan's
    // trailing click must not open the session it started on.
    const tile = page.getByRole("link", { name: /^Open details for / }).first();
    await tile.scrollIntoViewIfNeeded();
    // scrollIntoViewIfNeeded knows nothing about the sticky header, which
    // overlays the top of the grid: a tile parked under it takes the
    // pointerdown on the header instead of the scroller, and no pan starts.
    const headBottom = await page
      .locator("[data-room-lanes-head]")
      .first()
      .evaluate((el) => el.getBoundingClientRect().bottom);
    const parked = await tile.boundingBox();
    expect(parked).not.toBeNull();
    if (!parked) return;
    if (parked.y < headBottom + 8) {
      await page.evaluate(
        (dy) => {
          const app = document.querySelector(".app-scroll");
          if (app) app.scrollTop -= dy;
        },
        headBottom + 8 - parked.y,
      );
    }
    const box = await tile.boundingBox();
    expect(box).not.toBeNull();
    if (!box) return;
    const grabbed = await body.evaluate((el) => el.scrollLeft);
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.keyboard.down("Space");
    await expect(body).toHaveClass(/room-lanes-pan-ready/);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + 120, box.y + box.height / 2, { steps: 5 });
    await page.mouse.up();
    await page.keyboard.up("Space");
    await expect.poll(() => body.evaluate((el) => el.scrollLeft)).toBeLessThan(grabbed);
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page).toHaveURL(/\?view=rooms$/);

    // Space held over the sticky head must be swallowed like over the grid —
    // its default pages the app scroller, and with the key auto-repeating the
    // page ran away from under the pan (the head is where a pan often parks
    // the pointer, since it overlays the grid's top edge).
    const headBox = await page.locator("[data-room-lanes-head]").first().boundingBox();
    expect(headBox).not.toBeNull();
    if (!headBox) return;
    await page.mouse.move(headBox.x + headBox.width / 2, headBox.y + headBox.height / 2);
    const topAtHead = await appTop();
    await page.keyboard.down("Space");
    await page.keyboard.down("Space");
    await page.keyboard.up("Space");
    await page.waitForTimeout(200);
    expect(await appTop()).toBe(topAtHead);
  });
});

test("overnight bookmark copies share one state and one request", async ({
  browser,
  browserName,
}) => {
  test.skip(browserName === "firefox", "Mutates bookmark state shared across browser projects");

  const context = await browser.newContext({
    storageState: path.join(__dirname, "..", ".auth-state-superuser.json"),
  });
  const page = await context.newPage();
  await page.goto(DENSE_EVENT_URL);

  const buttons = page.locator(".bookmark-toggle");
  const sessionId = await buttons.evaluateAll((elements) => {
    const daysBySession = new Map<string, Set<string>>();
    for (const button of elements as HTMLElement[]) {
      const id = button.dataset.sessionId;
      const day = button.closest<HTMLElement>(".session")?.dataset.day;
      if (!id || !day) continue;
      const days = daysBySession.get(id) ?? new Set<string>();
      days.add(day);
      daysBySession.set(id, days);
    }
    return [...daysBySession].find(([, days]) => days.size > 1)?.[0] ?? null;
  });
  if (!sessionId) throw new Error("The fixture needs an overnight session");

  const copies = page.locator(`.bookmark-toggle[data-session-id="${sessionId}"]`);
  await expect(copies).toHaveCount(2);
  const initialStates = await copies.evaluateAll((elements) =>
    elements.map((element) => element.getAttribute("aria-pressed")),
  );
  expect(new Set(initialStates).size).toBe(1);
  expect(new Set(await copies.locator(".bookmark-count").allTextContents()).size).toBe(1);

  const source = copies.first();
  const copy = copies.nth(1);
  const wasBookmarked = (await source.getAttribute("aria-pressed")) === "true";
  let requests = 0;
  // The second click has to land while the first request is still in flight,
  // so hold the response until the test releases it rather than racing a sleep
  // against Playwright's actionability checks.
  let release = (): void => {};
  const inFlight = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(/\/bookmark\/$/, async (route) => {
    requests += 1;
    await inFlight;
    await route.continue();
  });

  const expectedState = String(!wasBookmarked);
  const responded = page.waitForResponse(/\/bookmark\/$/);
  await source.click();
  // The optimistic paint lands with the click and the copy stays interactive,
  // so the two states meet without a :disabled fade blinking between them; the
  // second click is dropped by the in-flight guard, not by the DOM.
  await expect(copy).toHaveAttribute("aria-pressed", expectedState);
  await expect(copy).toBeEnabled();
  await copy.click({ force: true });
  release();
  await responded;

  for (const button of await copies.all()) {
    await expect(button).toHaveAttribute("aria-pressed", expectedState);
  }
  expect(new Set(await copies.locator(".bookmark-count").allTextContents()).size).toBe(1);
  expect(requests).toBe(1);

  await page.locator("#status-filter").selectOption("my-bookmarked");
  const hiddenStates = await copies.evaluateAll((elements) =>
    elements.map((button) => button.closest<HTMLElement>(".session-wrapper")?.hidden),
  );
  expect(hiddenStates.every((hidden) => hidden === wasBookmarked)).toBe(true);

  await context.close();
});

// On a phone the ledger's time leaves the flex line and centres itself against
// the whole two-line row, so any padding that belongs to that shared line lands
// the pair half of itself below where it should sit.
test("the ledger's stacked time lines up with the title and the meta line", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await page.goto(DENSE_EVENT_URL);
  await expect(page.locator(".session-grid .session").first()).toBeVisible();

  const offsets = await page.evaluate(() => {
    const row = document.querySelector(".session-grid .session")!;
    const inkMiddle = (node: Node) => {
      const range = document.createRange();
      range.selectNodeContents(node);
      const box = range.getBoundingClientRect();
      return (box.top + box.bottom) / 2;
    };
    const time = row.querySelector("span.tabular-nums")!;
    const startLine = [...time.childNodes].find(
      (node) => node.nodeType === Node.TEXT_NODE && node.textContent!.trim(),
    )!;
    return {
      start: inkMiddle(startLine) - inkMiddle(row.querySelector(".font-semibold")!),
      end: inkMiddle(time.querySelector("span.block")!) - inkMiddle(row.querySelector("[title]")!),
    };
  });

  expect(Math.abs(offsets.start)).toBeLessThan(2);
  expect(Math.abs(offsets.end)).toBeLessThan(2);
});

test.describe("Enrollment filter", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(EVENT_URL);
    await page.getByRole("button", { exact: true, name: "Filters" }).click();
  });

  test("narrows the schedule to the sessions that take sign-up", async ({ page }) => {
    await expect(page.getByRole("link", { name: /^Open details for / })).toHaveCount(3);
    await markPage(page);

    await enrollmentOnly(page).check();

    await expect(card(page, MEGA)).toBeVisible();
    await expect(card(page, NEON)).toBeVisible();
    await expect(card(page, COZY)).toBeHidden();
    // A filter, not a view: the URL mirror is a replaceState, so no request
    // goes out and nothing reloads.
    await expect.poll(() => new URL(page.url()).searchParams.get("enrollment")).toBe("1");
    expect(new URL(page.url()).pathname).toBe(EVENT_URL);
    expect(await stayedOnPage(page)).toBe(true);
  });

  test("clearing its chip brings the whole schedule back", async ({ page }) => {
    await enrollmentOnly(page).check();
    await expect(card(page, COZY)).toBeHidden();

    await page.getByRole("button", { name: "Remove filter" }).click();

    await expect(card(page, COZY)).toBeVisible();
    await expect(enrollmentOnly(page)).not.toBeChecked();
  });

  test("search still filters the sessions it left on screen", async ({ page }) => {
    await enrollmentOnly(page).check();

    await page.getByRole("textbox", { name: "Search by name or text..." }).fill("mega");

    await expect(card(page, MEGA)).toBeVisible();
    await expect(card(page, NEON)).toBeHidden();
  });
});
