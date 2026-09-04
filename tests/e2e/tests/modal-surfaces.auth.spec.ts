import { type Locator, type Page } from "@playwright/test";
import path from "node:path";

import { expect, test } from "./helpers/fixtures";

// The cap is a cross-file name — --modal-max-h, defined in modal.css — and an
// unresolvable var() computes to max-height:none in silence: no console error,
// no build error, no lint error. Nothing else in the suite notices a modal that
// has stopped capping itself, which is how #1030's bug looked on iOS.
const expectCappedToViewport = async (page: Page, modal: Locator) => {
  const visible = await page.evaluate(() => visualViewport!.height * visualViewport!.scale);
  await expect
    .poll(() =>
      modal.evaluate((el) => {
        const { maxHeight } = getComputedStyle(el);
        return maxHeight === "none" ? maxHeight : Number.parseFloat(maxHeight);
      }),
    )
    .toBeCloseTo(visible * 0.9, 0);
};

const expectPageScrollLocked = async (page: Page) => {
  const pageScrollLocked = await page.evaluate(() => {
    const bodyOverflow = getComputedStyle(document.body).overflowY;
    const bodyPosition = getComputedStyle(document.body).position;
    return bodyOverflow === "hidden" || bodyPosition === "fixed";
  });
  expect(pageScrollLocked).toBe(true);
};

test.describe("Modal surfaces using page scroll lock", () => {
  test("opens and closes the session detail modal", async ({ browser }) => {
    const context = await browser.newContext({
      storageState: path.join(__dirname, "..", ".auth-state-superuser.json"),
    });
    const page = await context.newPage();

    await page.goto("/event/autumn-open/");

    await page.getByRole("link", { name: "Open details for Mega Strategy Lab" }).press("Enter");

    const dialog = page.getByRole("dialog", { name: "Mega Strategy Lab" });
    await expect(dialog).toBeVisible();
    await expectPageScrollLocked(page);
    await expectCappedToViewport(page, dialog);

    await dialog.getByRole("button", { name: "Close" }).click();
    await expect(dialog).toBeHidden();

    await context.close();
  });
});
