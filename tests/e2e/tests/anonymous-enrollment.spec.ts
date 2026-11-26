import { type Page } from "@playwright/test";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";

// NOTE: lantern-fair allows enrollment without an account (bootstrap_data.py).
// Lantern Walk has room; Cellar Duel's one seat belongs to a seeded member, so
// a second signup there can only wait. Every run activates a fresh code under
// a name of its own and hands back what that code took.
const EVENT_URL = "/event/lantern-fair/";

const openSession = async (page: Page, title: string) => {
  // NOTE: the card's description sits above its stretched link, so a pointer
  // click lands on the text; the keyboard reaches the link itself.
  await page.getByRole("link", { name: `Open details for ${title}` }).press("Enter");
  const dialog = page.getByRole("dialog", { name: title });
  await expect(dialog).toBeVisible();
  return dialog;
};

// The modal's way in names the state: a code with no seat there enrolls, a
// code holding one manages it.
const enrollmentPage = async (
  page: Page,
  title: string,
  way: "Enroll Anonymously" | "Manage Enrollment",
) => {
  const dialog = await openSession(page, title);
  await dialog.getByRole("link", { name: way }).click();
  await expect(page.getByRole("heading", { name: "Anonymous Enrollment" })).toBeVisible();
};

const closeSession = async (page: Page, title: string) => {
  const dialog = page.getByRole("dialog", { name: title });
  await dialog.getByRole("button", { name: "Close" }).click();
  await expect(dialog).toBeHidden();
};

const openRoster = async (page: Page, title: string) => {
  const dialog = await openSession(page, title);
  await dialog.getByRole("button", { name: "Participants" }).click();
  const roster = dialog.getByRole("dialog", { name: "Participants" });
  await expect(roster).toBeVisible();
  return { dialog, roster };
};

// Errors and warnings are alerts, successes are statuses; both land here.
const flash = (page: Page, text: string) =>
  page.getByRole("region", { name: "Notifications" }).getByText(text);

const shownCode = (page: Page) =>
  page.getByRole("paragraph").filter({ hasText: "Your Anonymous Code:" }).getByRole("strong");

test("a visitor signs up with a code, waits for a full session, and gives both back from another browser", async ({
  page,
  browser,
}, testInfo) => {
  const name = `Wren ${testInfo.retry}${Date.now() % 100_000}`;

  await page.goto(`${EVENT_URL}anonymous/do/activate`);
  await expect(page.getByRole("heading", { name: "Anonymous Mode Active" })).toBeVisible();
  const code = (await shownCode(page).innerText()).trim();
  expect(code).toMatch(/^\S{6}$/);

  await enrollmentPage(page, "Lantern Walk", "Enroll Anonymously");
  await expect(page.getByText(code, { exact: true })).toBeVisible();

  // Spaces pass the browser's required check; the server has to refuse them.
  await page.getByLabel("Name").fill("   ");
  await page.getByRole("button", { name: "Complete Enrollment" }).click();
  await expect(flash(page, "Name is required.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Anonymous Enrollment" })).toBeVisible();

  await page.getByLabel("Name").fill(name);
  await page.getByRole("button", { name: "Complete Enrollment" }).click();
  await expect(page).toHaveURL(new RegExp(`${EVENT_URL}$`));
  await expect(flash(page, "Successfully enrolled in session: Lantern Walk")).toBeVisible();
  const lantern = await openRoster(page, "Lantern Walk");
  await expect(lantern.roster.getByRole("img", { name })).toBeVisible();
  await closeSession(page, "Lantern Walk");

  // The code already carries a name, so the second signup asks for none.
  await enrollmentPage(page, "Cellar Duel", "Enroll Anonymously");
  await expect(page.getByLabel("Name")).toHaveCount(0);
  await page.getByRole("button", { name: "Enroll Now" }).click();
  await expect(
    flash(page, "Session is full. You have been added to the waiting list for: Cellar Duel"),
  ).toBeVisible();
  const duel = await openRoster(page, "Cellar Duel");
  await expect(duel.dialog.locator("[data-roster]")).toContainText("1/1");
  await expect(duel.dialog.locator("[data-roster]")).toContainText("1 waiting");
  // Waiting is a count on the trigger; the person lands under Waiting List.
  await expect(duel.roster.getByRole("heading", { name: "Waiting List" })).toBeVisible();
  await expect(duel.roster.getByText(name, { exact: true })).toBeVisible();
  await closeSession(page, "Cellar Duel");

  // Another browser knows nothing about the first one; the code is all it has.
  const other = await browser.newContext();
  const otherPage = await other.newPage();
  await otherPage.goto(`${EVENT_URL}anonymous/do/activate`);
  await expect(shownCode(otherPage)).not.toHaveText(code);
  await otherPage.getByRole("link", { name: /Enter Different Code/ }).click();
  const codeDialog = otherPage.getByRole("dialog", { name: "Enter Different Code" });
  await codeDialog.getByLabel("Anonymous Code").fill(code);
  await codeDialog.getByRole("button", { name: "Switch to This Code" }).click();
  await expect(flash(otherPage, "Code loaded successfully")).toBeVisible();
  await expect(shownCode(otherPage)).toHaveText(code);

  await enrollmentPage(otherPage, "Cellar Duel", "Manage Enrollment");
  await expect(otherPage.getByText("Status: On waiting list")).toBeVisible();
  await otherPage.getByRole("button", { name: "Cancel Enrollment" }).click();
  await expect(
    flash(otherPage, "Successfully cancelled enrollment in session: Cellar Duel"),
  ).toBeVisible();

  await enrollmentPage(otherPage, "Lantern Walk", "Manage Enrollment");
  await expect(otherPage.getByText(`${name} is already enrolled in this session.`)).toBeVisible();
  await otherPage.getByRole("button", { name: "Cancel Enrollment" }).click();
  await expect(
    flash(otherPage, "Successfully cancelled enrollment in session: Lantern Walk"),
  ).toBeVisible();
  await other.close();

  // The first browser sees both handed back, and is offered the way in again.
  await page.goto(EVENT_URL);
  const clearedDuel = await openSession(page, "Cellar Duel");
  await expect(clearedDuel.locator("[data-roster]")).not.toContainText("waiting");
  await closeSession(page, "Cellar Duel");
  const walk = await openRoster(page, "Lantern Walk");
  await expect(walk.roster.getByRole("img", { name })).toHaveCount(0);
  await expect(walk.dialog.getByRole("link", { name: "Enroll Anonymously" })).toBeVisible();

  await attachArtifacts(testInfo, {
    name: "anonymous-enrollment",
    region: walk.dialog,
    facts: { code, name, lanternWalk: (await walk.dialog.innerText()).trim() },
  });
});
