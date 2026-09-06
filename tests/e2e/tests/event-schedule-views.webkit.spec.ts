import { expect, test } from "./helpers/fixtures";
import { DENSE_EVENT_URL } from "./helpers/urls";

// The rooms grid pans horizontally under a sticky header, and the sub-pixel
// disagreement the assertion allows for differs between engines — so this wants
// WebKit at a phone's width. It gets the desktop projects as well, which match
// every spec; the tolerance is written to hold in all of them.
test.describe("Rooms schedule on a phone", () => {
  test("a room's name stands over that room's sessions", async ({ page }) => {
    await page.goto(`${DENSE_EVENT_URL}?view=rooms`);
    const grid = page.getByRole("region", { name: "Rooms schedule" });
    const max = await grid.evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(max).toBeGreaterThanOrEqual(300);

    // A session announces the room it is in (aria-describedby), so the pair
    // to check is that room's heading and that session's tile — what the
    // reader actually reads together, rather than the two grids underneath.
    const tile = page.getByRole("link", { name: /^Open details for / }).first();
    const room = await tile.evaluate((link) => {
      const described = link.getAttribute("aria-describedby");
      const name = described ? document.getElementById(described)?.textContent : "";
      // "<space>, <room>" where a room sits in a named space.
      return (name ?? "").trim().split(",").pop()?.trim() ?? "";
    });
    expect(room).not.toBe("");
    // Visible only: the room filter carries the same name in a closed select.
    const heading = page.getByText(room, { exact: true }).filter({ visible: true }).first();

    // Sub-pixel, not exact, and it cannot be: the header's travel ends on the
    // grid's real width while scrollLeft tops out at an integer scrollWidth,
    // so the two disagree by that rounding — measured 0.62px (WebKit) and
    // 0.41px (Chromium) at full scroll on a phone, growing from 0. Under a
    // pixel is the honest bound, and every failure worth catching is orders
    // bigger: a sign flip is twice the overflow, a dead fallback all of it.
    // The two sit a fixed distance apart — different padding, same column — so
    // what is asserted is that the distance does not change as the grid pans. A
    // heading that lags its column moves relative to it; one that keeps step
    // does not, whatever padding sits between them. Read through the elements
    // rather than Playwright's box, which is null for a column clipped out of
    // the strip at full scroll.
    const offset = async () => {
      const [over, under] = await Promise.all([
        heading.evaluate((el) => el.getBoundingClientRect().x),
        tile.evaluate((el) => el.getBoundingClientRect().x),
      ]);
      return over - under;
    };
    const atRest = await offset();

    // The axis heading names the hour column and belongs to no room, so it
    // holds still while the columns travel under it. That is the behaviour
    // pinning it beside the grid rather than inside it, and making it paint its
    // own ground, exist for — nothing else here covers either.
    const axis = page.getByText("Time", { exact: true }).filter({ visible: true }).first();
    const axisAtRest = await axis.evaluate((el) => el.getBoundingClientRect().x);

    for (const left of [Math.floor(max / 3), max]) {
      await grid.evaluate((el, target) => {
        el.scrollLeft = target;
      }, left);
      await expect.poll(async () => Math.abs((await offset()) - atRest)).toBeLessThan(1);
      await expect
        .poll(async () =>
          Math.abs((await axis.evaluate((el) => el.getBoundingClientRect().x)) - axisAtRest),
        )
        .toBeLessThan(1);
    }
  });
});
