import { expect, type Locator, type Page } from "@playwright/test";

// NOTE: --modal-max-h is a cross-file name, and an unresolvable var() computes
// to max-height:none in silence. Nothing else in the suite notices a dialog
// that has stopped capping itself, so this reads the computed cap. The cap is
// 90dvh; with no browser chrome here, dvh and innerHeight agree.
export const expectCappedToViewport = async (page: Page, surface: Locator): Promise<void> => {
  const visible = await page.evaluate(() => window.innerHeight);
  await expect
    .poll(() =>
      surface.evaluate((el) => {
        const { maxHeight } = getComputedStyle(el);
        return maxHeight === "none" ? maxHeight : Number.parseFloat(maxHeight);
      }),
    )
    .toBeCloseTo(visible * 0.9, 0);
};
