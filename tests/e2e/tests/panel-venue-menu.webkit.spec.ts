import { attachArtifacts } from "./helpers/artifacts";
import { managerState } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

const VENUES = "/panel/event/thornwood-days/venues/";

test.describe("Venue actions on a phone", () => {
  // NOTE: the page opens at phone size rather than being resized mid-test. A
  // late `resize` closes a pinned menu (menu.ts), and WebKit can stop painting
  // after `setViewportSize`, which hangs `toBeInViewport` past its timeout.
  test.use({ storageState: managerState, viewport: { width: 375, height: 812 } });

  test("the last venue's menu is not cut off, so it can be deleted", async ({ page }, testInfo) => {
    const name = `Attic ${Date.now()}`;
    await page.goto(`${VENUES}create/`);
    await page.getByLabel("Name").fill(name);
    await page.getByRole("button", { name: "Create space" }).click();
    await page.waitForURL(`**${VENUES}`);

    const venue = page.getByRole("listitem").filter({ has: page.getByText(name, { exact: true }) });
    await venue.getByRole("button", { name: `More actions for ${name}` }).click();
    const remove = venue.getByRole("button", { name: "Delete" });
    await expect(remove).toBeInViewport();
    // NOTE: a trial click fails when anything else on the page covers the item.
    await venue.getByRole("link", { name: "Copy to event" }).click({ trial: true });
    await attachArtifacts(testInfo, {
      name: "venue-menu-phone",
      region: page.locator("body"),
      facts: { venue: name },
    });

    await remove.click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Confirm" }).click();
    await page.waitForURL(`**${VENUES}`);
    await expect(page.getByText(name, { exact: true })).toHaveCount(0);
  });
});
