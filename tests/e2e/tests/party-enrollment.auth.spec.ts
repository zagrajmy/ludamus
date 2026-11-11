import { type Locator, type Page } from "@playwright/test";
import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";

// NOTE: Maren Hearth manages one companion, Pip Hearth (bootstrap_data.py), and
// nobody else signs up on hearth-night. Two Chair Tale seats both of them;
// Last Chair Saga has one chair left, the other taken by a seeded regular.
test.use({ storageState: path.join(__dirname, "..", ".auth-state-e2e-hearth-host.json") });

const EVENT_URL = "/event/hearth-night/";
const HOST = "Maren Hearth";
const COMPANION = "Pip Hearth";

const openSession = async (page: Page, title: string) => {
  await page.goto(EVENT_URL);
  // NOTE: the card's description sits above its stretched link, so a pointer
  // click lands on the text; the keyboard reaches the link itself.
  await page.getByRole("link", { name: `Open details for ${title}` }).press("Enter");
  const dialog = page.getByRole("dialog", { name: title });
  await expect(dialog).toBeVisible();
  return dialog;
};

const roster = async (page: Page, title: string) => {
  const dialog = await openSession(page, title);
  await dialog.getByRole("tab", { name: /Participants/ }).click();
  return dialog.getByRole("tabpanel");
};

const enrollmentForm = async (page: Page, title: string) => {
  await openSession(page, title);
  await page
    .getByRole("dialog", { name: title })
    .getByRole("link", { name: "with others" })
    .click();
  await expect(page.getByRole("heading", { name: title, level: 1 })).toBeVisible();
  return page.getByRole("list").filter({ has: page.getByRole("checkbox") });
};

const row = (form: Locator, name: string) => form.getByRole("listitem").filter({ hasText: name });

// Unticking everyone and saving gives every seat and waiting place back. The
// tests start with it, so a retry after a failed run starts from the seed.
const leave = async (page: Page, title: string) => {
  const form = await enrollmentForm(page, title);
  const held = form
    .getByRole("listitem")
    .filter({ hasText: /Already enrolled|On the waiting list/ });
  const leaving = await held.count();
  if (leaving === 0) return;
  for (const box of await held.getByRole("checkbox").all()) await box.uncheck();
  await expect(form.getByText("Will leave the session")).toHaveCount(leaving);
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page).toHaveURL(new RegExp(`${EVENT_URL}`));
};

test.describe.configure({ mode: "serial" });

test.describe("Signing a companion up", () => {
  test("both get a seat where there is room, and both can give it back", async ({
    page,
  }, testInfo) => {
    await leave(page, "Two Chair Tale");

    const form = await enrollmentForm(page, "Two Chair Tale");
    await form.getByRole("checkbox", { name: `Include ${COMPANION}` }).check();
    await expect(row(form, HOST)).toContainText("Gets a seat");
    await expect(row(form, COMPANION)).toContainText("Gets a seat");
    await page.getByRole("button", { name: "Join this session" }).click();
    await expect(page).toHaveURL(new RegExp(`${EVENT_URL}`));

    const seated = await roster(page, "Two Chair Tale");
    // The panel reads top to bottom: who is seated, then who waits.
    await expect(seated).toHaveText(
      new RegExp(
        `Enrolled \\(2/2\\)[\\s\\S]*${HOST}[\\s\\S]*${COMPANION}[\\s\\S]*No one on the waiting list`,
      ),
    );
    await attachArtifacts(testInfo, {
      name: "party-enrollment-seated",
      region: page.getByRole("dialog", { name: "Two Chair Tale" }),
      facts: { session: "Two Chair Tale", enrolled: [HOST, COMPANION] },
    });

    await leave(page, "Two Chair Tale");
    await expect(await roster(page, "Two Chair Tale")).toHaveText("No participants enrolled yet.");
  });

  test("with one chair left the companion waits, and is told so before saving", async ({
    page,
  }, testInfo) => {
    await leave(page, "Last Chair Saga");

    const form = await enrollmentForm(page, "Last Chair Saga");
    await form.getByRole("checkbox", { name: `Include ${COMPANION}` }).check();
    await expect(row(form, HOST)).toContainText("Gets a seat");
    await expect(row(form, COMPANION)).toContainText("Joins the waiting list");
    await page.getByRole("button", { name: "Join this session" }).click();
    await expect(page).toHaveURL(new RegExp(`${EVENT_URL}`));

    const split = await roster(page, "Last Chair Saga");
    await expect(split).toHaveText(
      new RegExp(`Enrolled \\(2/2\\)[\\s\\S]*${HOST}[\\s\\S]*Waiting List[\\s\\S]*${COMPANION}`),
    );
    await attachArtifacts(testInfo, {
      name: "party-enrollment-waiting",
      region: page.getByRole("dialog", { name: "Last Chair Saga" }),
      facts: { session: "Last Chair Saga", seated: HOST, waiting: COMPANION },
    });

    await leave(page, "Last Chair Saga");
    const regularOnly = await roster(page, "Last Chair Saga");
    await expect(regularOnly.getByRole("heading", { name: "Enrolled (1/2)" })).toBeVisible();
    await expect(regularOnly.getByText(COMPANION)).toHaveCount(0);
  });
});
