import { type Page } from "@playwright/test";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";
import { settleViewTransitions } from "./helpers/view-transitions";

// NOTE: bootstrap_data.py seeds one covered and one bare session here, placeholders off.
const EVENT_URL = "/event/session-covers/";

const openSession = async (page: Page, title: string) => {
  // NOTE: the card's text sits above its stretched link; Enter reaches the link.
  await page.getByRole("link", { name: `Open details for ${title}` }).press("Enter");
  const dialog = page.getByRole("dialog", { name: title });
  await expect(dialog).toBeVisible();
  await settleViewTransitions(page);
  return dialog;
};

test.describe("Session modal cover", () => {
  test("opens under the session's cover", async ({ page }, testInfo) => {
    await page.goto(EVENT_URL);
    const dialog = await openSession(page, "Meeple Painting");

    const cover = dialog.locator("[data-cover-strip]");
    await expect(cover).toBeVisible();
    await expect(cover).toHaveAttribute("alt", "");
    await expect
      .poll(() => cover.evaluate((image: HTMLImageElement) => image.naturalWidth))
      .toBeGreaterThan(0);

    const coverBox = await cover.boundingBox();
    const titleBox = await dialog.getByRole("heading", { name: "Meeple Painting" }).boundingBox();
    if (!coverBox || !titleBox) throw new Error("modal cover or title has no box");
    expect(coverBox.y + coverBox.height).toBeLessThanOrEqual(titleBox.y);

    await attachArtifacts(testInfo, {
      name: "session-modal-cover",
      region: dialog,
      facts: { coverSrc: await cover.getAttribute("src"), coverBox, titleBox },
    });
  });

  test("shows no cover for a session without one", async ({ page }) => {
    await page.goto(EVENT_URL);
    const dialog = await openSession(page, "Blank Canvas");

    await expect(dialog.getByRole("heading", { name: "Blank Canvas" })).toBeVisible();
    await expect(dialog.locator("[data-cover-strip]")).toHaveCount(0);
  });

  test("drops the cover when the viewport is too short for it", async ({ page }) => {
    await page.setViewportSize({ width: 844, height: 390 });
    await page.goto(EVENT_URL);
    const dialog = await openSession(page, "Meeple Painting");

    await expect(dialog.locator("[data-cover-strip]")).toBeHidden();
    await expect(dialog.getByText("Bring a brush; the meeples are on us.")).toBeVisible();
  });
});
