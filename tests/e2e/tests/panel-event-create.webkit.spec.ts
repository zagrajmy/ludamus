import { attachArtifacts } from "./helpers/artifacts";
import { managerState } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

test.describe("Panel event creation on a phone", () => {
  test.use({ storageState: managerState });

  for (const { width, paired } of [
    { width: 375, paired: true },
    { width: 320, paired: false },
  ]) {
    test(`the form fits ${width}px without scrolling sideways`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 812 });
      await page.goto("/panel/events/new/");
      const form = page.getByRole("main").locator("form");
      await expect(page.getByRole("heading", { name: "New event" })).toBeVisible();
      const start = page.getByLabel("Start time");
      const end = page.getByLabel("End time");
      await start.fill("2001-05-04T10:00");
      await end.fill("2001-05-04T18:00");

      const overflow = await page.evaluate(() => {
        const scroller = document.getElementById("app-scroll")!;
        const viewport = document.documentElement.clientWidth;
        const fields = [...document.querySelectorAll("main form :is(input, select, textarea)")]
          .filter((field) => field.getBoundingClientRect().right > viewport)
          .map((field) => field.getAttribute("name"));
        return { sideways: scroller.scrollWidth - scroller.clientWidth, fields };
      });
      expect(overflow).toEqual({ sideways: 0, fields: [] });

      const [startBox, endBox] = [(await start.boundingBox())!, (await end.boundingBox())!];
      expect({ sameRow: startBox.y === endBox.y }).toEqual({ sameRow: paired });
      await attachArtifacts(testInfo, {
        name: `event-create-${width}px`,
        region: form,
        facts: { width, paired },
      });
    });
  }
});
