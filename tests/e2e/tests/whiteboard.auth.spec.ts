import { type Browser, devices, type Locator, type Page } from "@playwright/test";

import { attachArtifacts } from "./helpers/artifacts";
import { assertNoCspViolations, installCspViolationCollector } from "./helpers/csp";
import { expect, test } from "./helpers/fixtures";

// The board, end to end against the real board Worker (playwright.config.ts
// starts it on :8788; .env.e2e points BOARD_HOST at it). Unlike Parley,
// nothing here is faked: Django signs the passes, the Worker verifies them,
// runs the tldraw sync room and draws every die.

const GUEST = "Ania";
const PHONE = devices["Pixel 7"];

// The board's own controls sit in tldraw's bottom bar; the sheets they open
// are dialogs named after them.
const sheet = (page: Page, name: string): Locator => page.getByRole("dialog", { name });

async function openSheet(page: Page, name: string): Promise<Locator> {
  const panel = sheet(page, name);
  if (!(await panel.isVisible())) await page.getByRole("button", { name, exact: true }).click();
  await expect(panel).toBeVisible();
  return panel;
}

async function closeSheet(page: Page, name: string): Promise<void> {
  await sheet(page, name).getByRole("button", { name: "Close" }).click();
  await expect(sheet(page, name)).toBeHidden();
}

// What a person reads on the canvas; tldraw also measures text off-screen.
const onBoard = (page: Page, text: string): Locator =>
  page.getByTestId("canvas").getByText(text, { exact: true });

// A sticky note with words on it, put down at a point of the screen.
async function putNote(page: Page, { at, text }: { at: { x: number; y: number }; text: string }) {
  await page.getByTestId("tools.note").click();
  await page.mouse.click(at.x, at.y);
  await page.keyboard.type(text);
  await page.keyboard.press("Escape");
  await expect(onBoard(page, text)).toBeVisible();
}

async function guestAtPhone(browser: Browser, url: string): Promise<Page> {
  // NOTE: storageState undefined, not {}: the chromium-auth project's
  // signed-in state must not leak into the guest.
  const context = await browser.newContext({ ...PHONE, storageState: undefined });
  const page = await context.newPage();
  await installCspViolationCollector(page);
  await page.goto(url);
  return page;
}

const shoot = async (page: Page, name: string, facts: object) =>
  attachArtifacts(test.info(), { name, region: page.locator("body"), facts });

// The newest roll log entry as it reads, line by line, without its last
// line: the time, which each screen formats from its own clock.
async function newestRoll(dialog: Locator): Promise<string> {
  const entry = dialog.getByRole("listitem").first();
  await expect(entry).toBeVisible();
  const lines = (await entry.innerText()).split("\n").map((line) => line.trim());
  return lines.slice(0, -1).filter(Boolean).join(" ");
}

test("a creator and a guest share one board: drawing, dice, places, link reset", async ({
  browser,
  page,
}) => {
  test.setTimeout(180_000);
  await installCspViolationCollector(page);

  // The creator starts a board from "My boards".
  await page.goto("/boards/");
  await page.getByRole("button", { name: "New board" }).first().click();
  await expect(page).toHaveURL(/\/b\/\w+\/$/u);
  const boardUrl = page.url();
  const boardPath = new URL(boardUrl).pathname;
  await expect(page.getByRole("button", { name: "Dice", exact: true })).toBeVisible();

  // The guest opens the link on a phone and names themself once.
  const guest = await guestAtPhone(browser, boardUrl);
  await guest.getByLabel("Your name").fill(GUEST);
  await shoot(guest, "board-guest-name", { step: "guest names themself", name: GUEST });
  await guest.getByRole("button", { name: "Join the board" }).click();
  await expect(guest.getByRole("button", { name: "Dice", exact: true })).toBeVisible();

  // What the creator draws turns up on the guest's phone.
  await putNote(page, { at: { x: 200, y: 300 }, text: "Hello table" });
  await expect(onBoard(guest, "Hello table")).toBeVisible();

  // The guest rolls 2d6; both roll logs show the same dice.
  const guestDice = await openSheet(guest, "Dice");
  await guestDice.getByRole("button", { name: "Add d6" }).click();
  await guestDice.getByRole("button", { name: "Add d6" }).click();
  await guestDice.getByRole("button", { name: "Roll 2d6" }).click();
  await expect(guestDice.getByRole("listitem").first()).toContainText(GUEST);
  const rolled = await newestRoll(guestDice);
  const total = Number(/Total:\s*(\d+)/u.exec(rolled)?.[1]);
  expect(total).toBeGreaterThanOrEqual(2);
  expect(total).toBeLessThanOrEqual(12);

  const creatorDice = await openSheet(page, "Dice");
  await expect.poll(async () => newestRoll(creatorDice)).toBe(rolled);
  await shoot(guest, "board-guest-rolled", { step: "guest rolled 2d6", rolled });
  await shoot(page, "board-creator-sees-roll", { step: "creator sees the roll", rolled });
  await closeSheet(page, "Dice");
  await closeSheet(guest, "Dice");

  // The creator makes a place of a note off the guest's small screen; the
  // guest jumps to it from the places list.
  await putNote(page, { at: { x: 1100, y: 250 }, text: "The map" });
  const creatorPlaces = await openSheet(page, "Places");
  await creatorPlaces.getByRole("button", { name: "Add to places" }).click();
  await creatorPlaces.getByLabel("Place name").fill("The map");
  await creatorPlaces.getByRole("button", { name: "Save" }).click();
  await expect(creatorPlaces.getByRole("button", { name: "The map", exact: true })).toBeVisible();
  await closeSheet(page, "Places");

  const farNote = onBoard(guest, "The map");
  await expect(farNote).not.toBeInViewport();
  const guestPlaces = await openSheet(guest, "Places");
  await guestPlaces.getByRole("button", { name: "The map", exact: true }).click();
  await expect(sheet(guest, "Places")).toBeHidden();
  await expect(farNote).toBeInViewport();
  await shoot(guest, "board-guest-at-place", { step: "guest jumped to a place", place: "The map" });

  // From "My boards" the creator names the board, so its row is easy to
  // tell apart, then resets its link and opens the board again.
  const title = `Mörk Borg night ${Date.now()}`;
  await page.goto("/boards/");
  const byLink = page.getByRole("listitem").filter({ has: page.locator(`a[href="${boardPath}"]`) });
  await byLink.getByRole("button", { name: "Board actions" }).click();
  await byLink.getByRole("link", { name: "Rename" }).click();
  await page.getByLabel("Board name").fill(title);
  await page.getByRole("button", { name: "Save name" }).click();
  await expect(page.getByText("Board renamed.")).toBeVisible();

  const row = page.getByRole("listitem").filter({ hasText: title });
  await row.getByRole("button", { name: "Board actions" }).click();
  await row.getByRole("button", { name: /Reset link/u }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Reset link" }).click();
  await expect(page.getByText("The board has a new link.")).toBeVisible();
  await expect(page.locator(`a[href="${boardPath}"]`)).toHaveCount(0);
  await page.getByRole("link", { name: new RegExp(title, "u") }).click();
  await expect(page).not.toHaveURL(boardUrl);
  await expect(onBoard(page, "Hello table")).toBeVisible();

  // The new link version puts the guest, who only had the old link, out.
  await expect(
    guest.getByText("The board's link was reset. Ask its creator for the new one."),
  ).toBeVisible();
  await expect(guest.getByRole("link", { name: /^Back to / })).toBeVisible();
  await shoot(guest, "board-guest-link-reset", { step: "guest put out by the link reset" });
  await shoot(page, "board-creator-after-reset", { step: "creator back on the board" });

  await assertNoCspViolations(page);
  await assertNoCspViolations(guest);
  await guest.context().close();
});
