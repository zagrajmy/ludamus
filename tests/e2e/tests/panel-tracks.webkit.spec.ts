import { attachArtifacts } from "./helpers/artifacts";
import { managerState } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

const TRACKS_URL = "/panel/event/thornwood-days/tracks/";

test.describe("Tracks on a phone", () => {
  test.use({ storageState: managerState });

  test("a track fits the screen, and its actions are in reach", async ({ page }, testInfo) => {
    const name = `Władca pierścieni los drużyny pierścienia ${Date.now()}`;
    await page.goto(`${TRACKS_URL}create/`);
    await page.getByLabel("Name").fill(name);
    for (const room of ["Oak Room", "Birch Room", "Cedar Room"]) {
      await page.getByRole("checkbox", { name: room }).check();
    }
    await page.getByRole("checkbox", { name: "Local Manager" }).check();
    await page.getByRole("button", { name: "Create Track" }).click();
    await page.waitForURL(`**${TRACKS_URL}`);

    await page.setViewportSize({ width: 375, height: 812 });
    const main = page.getByRole("main");
    const track = main.getByText(name, { exact: true });
    await expect(track).toBeInViewport();

    const layout = await page.evaluate((trackName) => {
      const viewport = document.documentElement.clientWidth;
      const tableScrollers = [...document.querySelectorAll("main table")].map(
        (t) => t.parentElement!,
      );
      const sideways = [document.getElementById("app-scroll")!, ...tableScrollers]
        .map((el) => el.scrollWidth - el.clientWidth)
        .filter((overflow) => overflow > 0);
      const outside = [...document.querySelectorAll("main :is(a, button, li)")]
        .filter((el) => el.getBoundingClientRect().right > viewport)
        .map((el) => el.textContent?.trim());
      const cell = [...document.querySelectorAll("main td")].find(
        (td) => td.textContent?.trim() === trackName,
      )!;
      return { sideways, outside, nameIsWide: cell.getBoundingClientRect().width > viewport / 2 };
    }, name);
    expect(layout).toEqual({ sideways: [], outside: [], nameIsWide: true });
    await attachArtifacts(testInfo, { name: "tracks-phone", region: main, facts: { track: name } });

    const row = main.getByRole("row").filter({ hasText: name });
    await row.getByRole("button", { name: "Delete" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Confirm" }).click();
    await page.waitForURL(`**${TRACKS_URL}`);
    await expect(main.getByText(name, { exact: true })).toHaveCount(0);
  });
});
