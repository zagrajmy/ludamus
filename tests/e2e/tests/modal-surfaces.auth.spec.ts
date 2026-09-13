import { type Page } from "@playwright/test";
import path from "node:path";

import { expect, test } from "./helpers/fixtures";
import { expectCappedToViewport } from "./helpers/modal-cap";

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

  test("docks the session detail modal to the bottom edge on a phone", async ({ browser }) => {
    const viewport = { width: 375, height: 700 };
    const context = await browser.newContext({
      storageState: path.join(__dirname, "..", ".auth-state-superuser.json"),
      viewport,
    });
    const page = await context.newPage();

    await page.goto("/event/autumn-open/");
    await page.getByRole("link", { name: "Open details for Mega Strategy Lab" }).press("Enter");

    const dialog = page.getByRole("dialog", { name: "Mega Strategy Lab" });
    await expect(dialog).toBeVisible();
    await expectCappedToViewport(page, dialog);

    // The sheet runs edge to edge and ends on the viewport's bottom edge; the
    // open transition scales it in, so read the box once it has settled.
    await expect
      .poll(async () => {
        const box = await dialog.boundingBox();
        return box && { bottom: Math.round(box.y + box.height), width: Math.round(box.width) };
      })
      .toEqual({ bottom: viewport.height, width: viewport.width });

    await context.close();
  });
});
