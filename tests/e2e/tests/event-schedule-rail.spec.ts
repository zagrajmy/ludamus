import { expect, test } from "./helpers/fixtures";

const denseEventUrl = "/chronology/event/kapitularz-2025-anonymized/";

const appScrollTop = (page: import("@playwright/test").Page): Promise<number> =>
  page.evaluate(() => document.getElementById("app-scroll")?.scrollTop ?? 0);

test.describe("Event schedule hour rail", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(denseEventUrl);
  });

  test("clicking an hour link scrolls its section into view", async ({ page }) => {
    const rail = page.getByRole("navigation", { name: "Jump to time" });
    const hourLinks = rail.getByRole("link", { name: /^Jump to/ });
    await expect(hourLinks.first()).toBeVisible();

    const link = hourLinks.nth(8);
    const href = await link.getAttribute("href");
    expect(href).toMatch(/^#slot-/);

    expect(await appScrollTop(page)).toBe(0);
    await link.click();

    await expect(page.locator(href!)).toBeInViewport();
    await expect.poll(() => appScrollTop(page)).toBeGreaterThan(0);
  });

  test("hour links are not natively draggable", async ({ page }) => {
    const rail = page.getByRole("navigation", { name: "Jump to time" });
    const hourLinks = rail.getByRole("link", { name: /^Jump to/ });
    await expect(hourLinks.first()).toHaveAttribute("draggable", "false");
  });

  test("long-press on a marker cannot open the current page in a new tab", async ({ page }) => {
    const rail = page.getByRole("navigation", { name: "Jump to time" });
    const link = rail.getByRole("link", { name: /^Jump to/ }).first();
    await expect(link).toBeVisible();

    const prevented = await link.evaluate((el) => {
      const event = new MouseEvent("contextmenu", { bubbles: true, cancelable: true });
      el.dispatchEvent(event);
      return event.defaultPrevented;
    });
    expect(prevented).toBe(true);
  });

  test("drag-scrubbing scrolls the schedule and shows the grabbing cursor", async ({
    browserName,
    isMobile,
    page,
  }) => {
    test.skip(isMobile, "hover cursors are meaningless on touch devices");
    test.skip(
      browserName === "firefox",
      "Playwright's Firefox driver dispatches no pointerup/mouseup after a drag, so the scrub never ends under automation (real Firefox fires mouseup)",
    );

    const rail = page.getByRole("navigation", { name: "Jump to time" });
    const hourLinks = rail.getByRole("link", { name: /^Jump to/ });
    await expect(hourLinks.first()).toBeVisible();

    const cursorOf = (locator: typeof rail): Promise<string> =>
      locator.evaluate((el) => getComputedStyle(el).cursor);

    expect(await cursorOf(hourLinks.first())).toBe("pointer");

    const box = await rail.boundingBox();
    expect(box).not.toBeNull();
    const x = box!.x + box!.width / 2;
    const yStart = box!.y + 40;

    await page.mouse.move(x, yStart);
    await page.mouse.down();
    await page.mouse.move(x, yStart + 120, { steps: 8 });

    await expect.poll(() => cursorOf(rail)).toBe("grabbing");
    expect(await cursorOf(hourLinks.first())).toBe("grabbing");
    await expect.poll(() => appScrollTop(page)).toBeGreaterThan(0);

    await page.mouse.up();

    await expect.poll(() => cursorOf(rail)).not.toBe("grabbing");
    expect(await cursorOf(hourLinks.first())).toBe("pointer");
  });

  test("the rail refits when the viewport moves without a window resize", async ({ page }) => {
    const rail = page.getByRole("navigation", { name: "Jump to time" });
    await expect(rail.getByRole("link").first()).toBeVisible();

    // What iOS does on a toolbar collapse or a keyboard: the visual viewport
    // moves and no window resize follows. Playwright cannot drive that, so
    // stand in for it with the announcement app-viewport.ts makes after every
    // write — the path the rail actually listens on, and the one the window
    // resize in the test below would otherwise mask.
    await page.evaluate(() => {
      document.documentElement.style.setProperty("--app-vh", "360px");
      document.dispatchEvent(new Event("viewport:resized"));
    });

    await expect
      .poll(() => rail.evaluate((el) => el.scrollHeight - el.clientHeight))
      .toBeLessThanOrEqual(0);
  });

  test("the rail refits when the viewport shrinks", async ({ page }) => {
    const rail = page.getByRole("navigation", { name: "Jump to time" });
    await expect(rail.getByRole("link").first()).toBeVisible();

    await page.setViewportSize({ width: 1280, height: 400 });

    // The rail caps itself at --app-vh and clips the overflow, so it has to
    // thin its markers again whenever that cap moves. Overflowing here means
    // the last hours are unreachable, with nothing able to scroll them back.
    await expect
      .poll(() => rail.evaluate((el) => el.scrollHeight - el.clientHeight))
      .toBeLessThanOrEqual(0);
  });
});
