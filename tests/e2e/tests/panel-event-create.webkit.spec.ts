import { attachArtifacts } from "./helpers/artifacts";
import { managerState } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

test.describe("Panel event creation on a phone", () => {
  test.use({ storageState: managerState });

  test("the form fits a phone without scrolling sideways", async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto("/panel/events/new/");
    const form = page.getByRole("main").locator("form");
    await expect(page.getByRole("heading", { name: "New event" })).toBeVisible();
    await page.getByLabel("Start time").fill("2001-05-04T10:00");
    await page.getByLabel("End time").fill("2001-05-04T18:00");

    const overflow = await page.evaluate(() => {
      const scroller = document.getElementById("app-scroll")!;
      const viewport = document.documentElement.clientWidth;
      const fields = [...document.querySelectorAll("main form :is(input, select, textarea)")]
        .filter((field) => field.getBoundingClientRect().right > viewport)
        .map((field) => field.getAttribute("name"));
      return { sideways: scroller.scrollWidth - scroller.clientWidth, fields };
    });
    expect(overflow).toEqual({ sideways: 0, fields: [] });
    await attachArtifacts(testInfo, { name: "event-create-phone", region: form });
  });
});
