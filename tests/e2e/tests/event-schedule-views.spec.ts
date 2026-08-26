import { type Page } from "@playwright/test";

import { expect, test } from "./helpers/fixtures";

const EVENT_URL = "/event/autumn-open/";
// The dense seeded event: the only one over the compact-schedule threshold,
// so the only one that offers a second layout to switch to.
const DENSE_EVENT_URL = "/event/kapitularz-2025-anonymized/";
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

test.describe("Event schedule views", () => {
  test("the view switcher offers nothing when the schedule has one layout", async ({ page }) => {
    await page.goto(EVENT_URL);

    await expect(page.getByRole("tablist", { name: "Schedule view" })).toHaveCount(0);
  });

  test("the rooms tab swaps the layout in without leaving the page", async ({ page }) => {
    await page.goto(DENSE_EVENT_URL);
    await markPage(page);

    await page.getByRole("tab", { name: "Rooms" }).click();

    await expect(page.locator(".room-lanes").first()).toBeVisible();
    await expect(page).toHaveURL(/\?view=rooms$/);
    expect(await stayedOnPage(page)).toBe(true);
  });

  test("the grid offers sideways scrollbars on both edges", async ({ page }) => {
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);
    const head = page.locator("[data-room-lanes-head]").first();
    const foot = page.locator("[data-room-lanes-foot]").first();
    const body = page.locator("[data-room-lanes-scroll]").first();

    // Real scrollers — that is what puts a scrollbar at the top and the
    // bottom edge for mouse users. The body's own scrollbar yields to the
    // foot, which pins to the viewport.
    for (const handle of [head, foot]) {
      await expect(handle).toHaveCSS("overflow-x", "auto");
    }
    await expect(body).toHaveCSS("scrollbar-width", "none");

    // Targets derived from the actual overflow, so a shrunken fixture fails
    // on this precondition instead of an opaque clamped-scroll poll timeout.
    const budget = (handle: typeof head) =>
      handle.evaluate((el) => el.scrollWidth - el.clientWidth);
    const max = Math.min(await budget(head), await budget(foot));
    expect(max).toBeGreaterThanOrEqual(300);
    const far = Math.floor(max / 2);
    const near = Math.floor(max / 4);

    // Dragging either handle pans the grid, and the grid drags both along.
    await head.evaluate((el, left) => {
      el.scrollLeft = left;
    }, far);
    await expect.poll(() => body.evaluate((el) => el.scrollLeft)).toBe(far);
    await expect.poll(() => foot.evaluate((el) => el.scrollLeft)).toBe(far);

    await foot.evaluate((el, left) => {
      el.scrollLeft = left;
    }, near);
    await expect.poll(() => body.evaluate((el) => el.scrollLeft)).toBe(near);
    await expect.poll(() => head.evaluate((el) => el.scrollLeft)).toBe(near);
  });

  test("the header names the day the reader is looking at", async ({ page }) => {
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);
    const label = page.locator("[data-room-lanes-day-current]");
    const days = page.locator(".room-lanes-day");
    expect(await days.count()).toBeGreaterThan(1);

    const first = await days.first().innerText();
    expect(await label.innerText()).toBe(first);

    // Scroll the second day's heading under the header — the day the reader is
    // in, which is what the sticky copy has to say.
    const second = days.nth(1);
    await second.evaluate((el) => {
      el.scrollIntoView({ block: "start" });
    });
    await expect.poll(() => label.innerText()).toBe(await second.innerText());
  });

  test("a line marks the current moment on the grid", async ({ page }) => {
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);
    const firstLine = page.locator("[data-hour-start]").first();
    const firstHour = await firstLine.getAttribute("data-hour-start");
    const firstRow = await firstLine.getAttribute("data-lane-row");
    expect(firstHour).not.toBeNull();
    if (!firstHour) return;

    // Half past the programme's first hour: a row for the line to land in and
    // a fraction that is neither end of it.
    await page.clock.install({ time: new Date(Date.parse(firstHour) + 30 * 60_000) });
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);

    const marker = page.locator("[data-room-lanes-now]");
    await expect(marker).toBeVisible();
    await expect(page.locator("[data-room-lanes-now-time]")).not.toBeEmpty();
    const placed = await marker.evaluate((el) => ({
      frac: Number(el.style.getPropertyValue("--now-frac")),
      row: el.style.gridRow,
    }));
    expect(placed.row).toBe(firstRow);
    expect(placed.frac).toBeCloseTo(0.5, 2);

    // A day before the programme opens, no hour row owns the moment. The tick
    // is what has to notice, not a reload.
    await page.clock.setFixedTime(new Date(Date.parse(firstHour) - 24 * 3600 * 1000));
    await page.clock.runFor(60_000);
    await expect(marker).toBeHidden();
  });

  test("a line marks the seam between started and upcoming in the ledger", async ({ page }) => {
    await page.goto(DENSE_EVENT_URL);
    const firstStart = await page
      .locator(".session-grid .session-wrapper .session[data-start]")
      .first()
      .getAttribute("data-start");
    expect(firstStart).not.toBeNull();
    if (!firstStart) return;

    const now = Date.parse(firstStart) + 90 * 60_000;
    await page.clock.install({ time: new Date(now) });
    await page.goto(DENSE_EVENT_URL);

    // Exactly one seam, and it sits before the first row still to come.
    const marked = page.locator(".session-wrapper[data-now-at]");
    await expect(marked).toHaveCount(1);
    const starts = await page.locator(".session-grid .session-wrapper").evaluateAll((rows) =>
      rows.map((row) => ({
        marked: row.hasAttribute("data-now-at"),
        start: row.querySelector<HTMLElement>(".session")?.dataset.start ?? "",
      })),
    );
    const seam = starts.findIndex((row) => row.marked);
    expect(Date.parse(starts[seam].start)).toBeGreaterThan(now);
    expect(Date.parse(starts[seam - 1].start)).toBeLessThanOrEqual(now);
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

test.describe("Enrollment filter", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(EVENT_URL);
    await page.getByRole("button", { name: "Filters" }).click();
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

    await page.getByRole("textbox", { name: "Search sessions..." }).fill("mega");

    await expect(card(page, MEGA)).toBeVisible();
    await expect(card(page, NEON)).toBeHidden();
  });
});
