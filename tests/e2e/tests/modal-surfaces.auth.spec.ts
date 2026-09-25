import { devices, type Page } from "@playwright/test";
import path from "node:path";

import { expect, test } from "./helpers/fixtures";
import { expectCappedToViewport } from "./helpers/modal-cap";
import { settleViewTransitions } from "./helpers/view-transitions";

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

  test("keeps Edit as a named icon button in the phone footer", async ({ browser }) => {
    const context = await browser.newContext({
      ...devices["iPhone 14 Pro"],
      storageState: path.join(__dirname, "..", ".auth-state-superuser.json"),
    });
    const page = await context.newPage();

    await page.goto("/event/facilitator-edit-demo/");
    await page.getByRole("link", { name: "Open details for Own Table Demo" }).press("Enter");

    const dialog = page.getByRole("dialog", { name: "Own Table Demo" });
    await expect(dialog).toBeVisible();
    // The footer morphs in via a view transition; reading geometry before it
    // settles catches the footer mid-resize and makes this assertion flaky.
    await settleViewTransitions(page);

    // Edit keeps its accessible name but shows only the pencil, as a square
    // at the tap-target floor, so it never pushes the enroll control onto a
    // second line.
    const edit = dialog.getByRole("button", { name: "Edit session" });
    await expect(edit).toBeVisible();
    const editBox = await edit.boundingBox();
    expect(editBox).not.toBeNull();
    expect(Math.round(editBox!.width)).toBe(44);
    expect(Math.round(editBox!.height)).toBe(44);

    await context.close();
  });
});

test("a seatless session's modal offers the bookmark beside its time", async ({
  browser,
  browserName,
}) => {
  test.skip(browserName === "firefox", "Mutates bookmark state shared across browser projects");

  const context = await browser.newContext({
    ...devices["iPhone 14 Pro"],
    storageState: path.join(__dirname, "..", ".auth-state-superuser.json"),
  });
  const page = await context.newPage();

  await page.goto("/event/autumn-open/");
  await page
    .getByRole("link", { name: "Open details for Cozy Storytellers Circle" })
    .press("Enter");

  const dialog = page.getByRole("dialog", { name: "Cozy Storytellers Circle" });
  await expect(dialog).toBeVisible();
  await settleViewTransitions(page);

  const bookmark = dialog.getByRole("button", { name: "Bookmark session" });
  const close = dialog.getByRole("button", { name: "Close" });
  const time = dialog.getByText("Time", { exact: true }).locator("..");
  const [bookmarkBox, closeBox, timeBox] = await Promise.all([
    bookmark.boundingBox(),
    close.boundingBox(),
    time.boundingBox(),
  ]);
  expect(bookmarkBox && closeBox && timeBox).toBeTruthy();
  if (!bookmarkBox || !closeBox || !timeBox) return;
  expect(bookmarkBox.x + bookmarkBox.width).toBeCloseTo(closeBox.x + closeBox.width, 0);
  expect(bookmarkBox.y + bookmarkBox.height).toBeCloseTo(timeBox.y + timeBox.height, 0);

  // Each toggle paints twice (optimistic, then settled), and the settled paint
  // runs in the same tick that releases the in-flight guard. Counting paints
  // keeps the second click from landing while the first is still settling.
  await page.evaluate(() => {
    const scope = globalThis as unknown as { __bookmarkPaints: number };
    scope.__bookmarkPaints = 0;
    document.addEventListener("session:bookmark-changed", () => {
      scope.__bookmarkPaints += 1;
    });
  });
  const paints = () =>
    page.evaluate(() => (globalThis as unknown as { __bookmarkPaints: number }).__bookmarkPaints);

  const was = await bookmark.getAttribute("aria-pressed");
  const toggled = page.waitForResponse(/\/bookmark\/$/);
  await bookmark.click();
  expect((await toggled).ok()).toBe(true);
  await expect.poll(paints).toBe(2);
  await expect(bookmark).toHaveAttribute("aria-pressed", String(was !== "true"));
  // The count showing up or going away must not reflow the time box.
  expect((await time.boundingBox())?.width).toBe(timeBox.width);

  const restored = page.waitForResponse(/\/bookmark\/$/);
  await bookmark.click();
  expect((await restored).ok()).toBe(true);
  await expect.poll(paints).toBe(4);
  await expect(bookmark).toHaveAttribute("aria-pressed", String(was));

  await context.close();
});
