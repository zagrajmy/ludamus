import { type Page } from "@playwright/test";
import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { managerState } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

// NOTE: saffron-gathering has one scheduled session and no enrollment window
// (bootstrap_data.py). The organizer opens one and deletes it again; afterEach
// deletes whatever a failed run left, so a retry starts from the seed.
const SETTINGS_URL = "/panel/event/saffron-gathering/settings/enrollment/";
const EVENT_URL = "/event/saffron-gathering/";
const NOTICE = "Saffron sign-ups are open until the spice runs out.";
// A member who only looks: the seeded tester holds nothing on this event.
const memberState = path.join(__dirname, "..", ".auth-state.json");

// The form takes the wall clock without a zone; a day either side of now
// keeps the window open whatever zone the server reads it in.
const localInput = (offsetDays: number) =>
  new Date(Date.now() + offsetDays * 86_400_000).toISOString().slice(0, 16);

const flash = (page: Page, text: string) =>
  page.getByRole("region", { name: "Notifications" }).getByText(text);

// The same member's browser looks each time, so a page it kept from an
// earlier visit would show here.
const spiceRoute = async (page: Page) => {
  await page.goto(EVENT_URL);
  // NOTE: the card's description sits above its stretched link, so a pointer
  // click lands on the text; the keyboard reaches the link itself.
  await page.getByRole("link", { name: "Open details for Spice Route" }).press("Enter");
  const dialog = page.getByRole("dialog", { name: "Spice Route" });
  await expect(dialog).toBeVisible();
  return dialog;
};

const deleteWindows = async (page: Page) => {
  await page.goto(SETTINGS_URL);
  const remove = page.getByRole("button", { name: "Delete window" });
  while ((await remove.count()) > 0) {
    await remove.first().click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Delete window" }).click();
    await expect(flash(page, "Enrollment window deleted.")).toBeVisible();
  }
  await expect(page.getByRole("heading", { name: "Enrollment is closed" })).toBeVisible();
};

test.use({ storageState: managerState });

test.afterEach(async ({ page }) => {
  await deleteWindows(page);
});

test("an organizer opens enrollment, members are offered a seat, and deleting the window takes it away", async ({
  page,
  browser,
}, testInfo) => {
  const member = await browser.newContext({ storageState: memberState });
  const memberPage = await member.newPage();

  const before = await spiceRoute(memberPage);
  await expect(before.getByRole("button", { name: "Enroll", exact: true })).toHaveCount(0);
  await expect(memberPage.getByText(NOTICE)).toHaveCount(0);

  await page.goto(SETTINGS_URL);
  await expect(page.getByRole("heading", { name: "Enrollment is closed" })).toBeVisible();
  await page.getByRole("link", { name: "Add enrollment window" }).first().click();

  // Closing before it opens is refused, and the typed values survive.
  await page.getByRole("textbox", { name: "Enrollment opens" }).fill(localInput(1));
  await page.getByRole("textbox", { name: "Enrollment closes" }).fill(localInput(-1));
  await page.getByLabel("Enrollment notice").fill(NOTICE);
  await page.getByRole("button", { name: "Save window" }).click();
  await expect(page.getByText("Enrollment must close after it opens.")).toBeVisible();
  await expect(page.getByLabel("Enrollment notice")).toHaveValue(NOTICE);

  await page.getByRole("textbox", { name: "Enrollment opens" }).fill(localInput(-1));
  await page.getByRole("textbox", { name: "Enrollment closes" }).fill(localInput(30));
  await page.getByRole("button", { name: "Save window" }).click();
  await expect(flash(page, "Enrollment window created.")).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`${SETTINGS_URL}$`));
  await expect(page.getByRole("row").filter({ hasText: "Active" })).toHaveCount(1);

  const open = await spiceRoute(memberPage);
  await expect(memberPage.getByText("Enrollment Open", { exact: true })).toBeVisible();
  await expect(memberPage.getByText(NOTICE)).toBeVisible();
  await expect(open.getByRole("button", { name: "Enroll", exact: true })).toBeVisible();
  await attachArtifacts(testInfo, {
    name: "panel-enrollment-window-open",
    region: memberPage.getByRole("main"),
    facts: { notice: NOTICE, offered: "Enroll" },
  });

  await deleteWindows(page);
  const closed = await spiceRoute(memberPage);
  await expect(closed.getByRole("button", { name: "Enroll", exact: true })).toHaveCount(0);
  await expect(memberPage.getByText("Enrollment Open", { exact: true })).toHaveCount(0);
  await expect(memberPage.getByText(NOTICE)).toHaveCount(0);
  await member.close();
});
