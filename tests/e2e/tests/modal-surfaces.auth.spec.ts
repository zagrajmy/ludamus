import { devices, type Locator, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
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
    // The footer's own view-transition group still interpolates its scale for
    // a frame or two after settleViewTransitions resolves (its ::view-transition
    // animation can clear one frame before the box's final size actually
    // paints), so the box briefly reads a pixel or two off 44. Poll instead of
    // reading once, so the assertion waits out that last frame rather than
    // racing it.
    await expect.poll(async () => Math.round((await edit.boundingBox())!.width)).toBe(44);
    await expect.poll(async () => Math.round((await edit.boundingBox())!.height)).toBe(44);

    await context.close();
  });
});

test("a seatless session's modal offers the bookmark at the end of its facts", async ({
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
  const facts = dialog.locator("[data-session-facts]");
  const factsList = facts.locator("> :first-child");
  const listWidth = (await factsList.boundingBox())?.width;
  const [bookmarkBox, closeBox, factsBox] = await Promise.all([
    bookmark.boundingBox(),
    close.boundingBox(),
    facts.boundingBox(),
  ]);
  expect(bookmarkBox && closeBox && factsBox).toBeTruthy();
  if (!bookmarkBox || !closeBox || !factsBox) return;
  expect(bookmarkBox.x + bookmarkBox.width).toBeCloseTo(closeBox.x + closeBox.width, 0);
  expect(bookmarkBox.y + bookmarkBox.height).toBeCloseTo(factsBox.y + factsBox.height, 0);

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
  // The count showing up or going away must not take width from the facts.
  expect((await factsList.boundingBox())?.width).toBe(listWidth);

  const restored = page.waitForResponse(/\/bookmark\/$/);
  await bookmark.click();
  expect((await restored).ok()).toBe(true);
  await expect.poll(paints).toBe(4);
  await expect(bookmark).toHaveAttribute("aria-pressed", String(was));

  await context.close();
});

test("saving the session from its modal keeps the heading's look and shows a new cover", async ({
  browser,
  browserName,
}) => {
  test.skip(browserName === "firefox", "Mutates the seeded session shared across browser projects");

  const context = await browser.newContext({
    storageState: path.join(__dirname, "..", ".auth-state-superuser.json"),
  });
  const page = await context.newPage();
  const cover = readFileSync(
    path.join(
      __dirname,
      "..",
      "..",
      "..",
      "src",
      "ludamus",
      "static",
      "placeholder-images",
      "01.webp",
    ),
  );
  const open = async (title: RegExp | string = "Own Table Demo") => {
    await page.goto("/event/facilitator-edit-demo/");
    await page.getByRole("link", { name: /^Open details for Own Table Demo/u }).press("Enter");
    const dialog = page.getByRole("dialog", { name: title });
    await expect(dialog).toBeVisible();
    return dialog;
  };
  // A save closes the dialog; the next open fetches the session fresh.
  const save = async (dialog: Locator) => {
    await dialog.getByRole("button", { name: "Save changes" }).click();
    await expect(dialog).toBeHidden();
  };

  try {
    let dialog = await open();
    await expect(dialog.locator("[data-cover-image]")).toHaveCount(0);

    await dialog.getByRole("button", { name: "Edit session" }).click();
    await dialog.locator('input[name="cover_image"]').setInputFiles({
      buffer: cover,
      mimeType: "image/webp",
      name: "cover.webp",
    });
    await save(dialog);
    dialog = await open();
    await expect(dialog.locator("[data-cover-image]")).toBeVisible();

    // A renamed title lands in the heading on the cover, still white.
    await dialog.getByRole("button", { name: "Edit session" }).click();
    await dialog.getByLabel("Title").fill("Own Table Demo, renamed");
    await save(dialog);
    dialog = await open("Own Table Demo, renamed");
    const heading = dialog.getByRole("heading", { name: "Own Table Demo, renamed" });
    await expect(heading).toHaveCSS("color", "rgb(255, 255, 255)");
  } finally {
    // Put the seeded session back for the other specs.
    const dialog = await open(/Own Table Demo/u);
    await dialog.getByRole("button", { name: "Edit session" }).click();
    await dialog.getByLabel("Title").fill("Own Table Demo");
    const remove = dialog.getByRole("button", { name: "Remove image" });
    if (await remove.isVisible()) {
      await remove.click();
    }
    await save(dialog);
    await context.close();
  }
});
