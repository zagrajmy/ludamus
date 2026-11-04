import { expect, test } from "./helpers/fixtures";

// User-centric tests (Kent C. Dodds style): drive the controls the way a person
// does — find them by their accessible role/name, act, and assert on the state
// the user can perceive (pressed/checked, persistence) — never on CSS classes,
// data-* hooks, or the Web Audio internals.

test.describe("interface sound toggle", () => {
  const toggle = (page: import("@playwright/test").Page) =>
    page.getByRole("checkbox", { name: /interface sound/i });
  const pressToggle = async (page: import("@playwright/test").Page): Promise<void> => {
    await toggle(page).locator("xpath=ancestor::label[1]").click();
  };

  test("starts on and turns off when the user presses it", async ({ page }) => {
    await page.goto("/design/");

    await expect(toggle(page)).toBeChecked();

    await pressToggle(page);

    await expect(toggle(page)).not.toBeChecked();
  });

  test("remembers the choice across a page reload", async ({ page }) => {
    await page.goto("/design/");

    await expect(toggle(page)).toBeChecked();
    await pressToggle(page);
    await expect(toggle(page)).not.toBeChecked();

    // commit, not load/domcontentloaded: `load` makes the test hostage to the
    // third-party font requests the page fires, and Firefox intermittently
    // misses the `domcontentloaded` lifecycle event on reload and hangs. The
    // assertion below retries, so returning at navigation commit is enough.
    //
    // Firefox's navigation driver also occasionally hangs on `commit` itself,
    // or drops its response binding mid-reload ("was not bound in the
    // connection") — a driver-level flake, not an app bug (see the flaky-test
    // report this fixes). Bound the reload so a hung attempt fails fast, and
    // retry the reload+check as a unit instead of burning the whole test
    // timeout on one stuck attempt.
    await expect(async () => {
      await page.reload({ waitUntil: "commit", timeout: 20_000 });
      await expect(toggle(page)).not.toBeChecked();
    }).toPass({ timeout: 60_000 });
  });
});

test.describe("segmented switcher", () => {
  test("shows its configured choice and lets the user pick another", async ({ page }) => {
    await page.goto("/design/");

    // The design gallery configures the switcher with "Grid view" selected.
    await expect(page.getByRole("radio", { name: /grid view/i })).toBeChecked();
    await expect(page.getByRole("radio", { name: /list view/i })).not.toBeChecked();

    // Activate "List view" the way a person does: click the visible segment.
    // The radio itself is sr-only, so we find it by its accessible name and
    // click its enclosing label (the visible control).
    await page
      .getByRole("radio", { name: /list view/i })
      .locator("xpath=ancestor::label[1]")
      .click();

    await expect(page.getByRole("radio", { name: /list view/i })).toBeChecked();
    await expect(page.getByRole("radio", { name: /grid view/i })).not.toBeChecked();
  });
});

// A finger that scrolls the schedule lands on a card's link first, and every
// scroll starting there used to sound the press cue. The cue is the thing
// perceived, so this counts the sounds rendered; no control exposes them.
test.describe("press sound on a touch screen", () => {
  test.use({ hasTouch: true, viewport: { height: 844, width: 390 } });

  test("a scroll that starts on a card is silent, a tap is not", async ({ browserName, page }) => {
    test.skip(browserName !== "chromium", "Raw touch input needs the Chromium protocol");

    await page.addInitScript(() => {
      const counter = globalThis as unknown as { soundsRendered: number };
      counter.soundsRendered = 0;
      const { createGain } = AudioContext.prototype;
      AudioContext.prototype.createGain = function (this: AudioContext) {
        counter.soundsRendered += 1;
        return createGain.call(this);
      };
    });
    const rendered = () =>
      page.evaluate(() => (globalThis as unknown as { soundsRendered: number }).soundsRendered);

    await page.goto("/event/autumn-open/");
    const title = page
      .getByRole("article")
      .filter({ hasText: "Cozy Storytellers Circle" })
      .getByRole("heading", { name: "Cozy Storytellers Circle" });
    await title.evaluate((element) => {
      element.scrollIntoView({ block: "center" });
    });
    const box = await title.boundingBox();
    if (!box) throw new Error("Card title has no box");
    const scroller = page.locator("#app-scroll");
    const before = await scroller.evaluate((element) => element.scrollTop);

    // A finger dragged up the screen from the card's title, the way a reader
    // scrolls past it.
    const cdp = await page.context().newCDPSession(page);
    const x = box.x + 10;
    const startY = box.y + box.height / 2;
    await cdp.send("Input.dispatchTouchEvent", {
      touchPoints: [{ x, y: startY }],
      type: "touchStart",
    });
    for (let step = 1; step <= 15; step += 1) {
      await cdp.send("Input.dispatchTouchEvent", {
        touchPoints: [{ x, y: startY - step * 15 }],
        type: "touchMove",
      });
    }
    await cdp.send("Input.dispatchTouchEvent", { touchPoints: [], type: "touchEnd" });

    await expect
      .poll(() => scroller.evaluate((element) => element.scrollTop))
      .toBeGreaterThan(before);
    // NOTE: a context the page has not resumed yet renders a beat after play().
    await page.waitForTimeout(300);
    expect(await rendered()).toBe(0);

    await page.getByRole("button", { exact: true, name: "Filters" }).tap();
    await expect.poll(rendered).toBeGreaterThan(0);
  });
});
