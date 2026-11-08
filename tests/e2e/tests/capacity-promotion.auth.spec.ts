import { type Browser, type Page } from "@playwright/test";
import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { managerState } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

// NOTE: every Harbor Siege on tidewater-moot seats one, held by a seeded
// member, with Ilse First and then Otto Second waiting (bootstrap_data.py). A
// raised limit cannot be taken back, so each attempt takes the session of its
// own number: a retry tests the feature, not the last attempt's leftovers.
const EVENT_URL = "/event/tidewater-moot/";
const PANEL_URL = "/panel/event/tidewater-moot/proposals/?status=all";
const stateOf = (slug: string) => path.join(__dirname, "..", `.auth-state-${slug}.json`);

const openSession = async (page: Page, title: string) => {
  await page.goto(EVENT_URL);
  // NOTE: the card's description sits above its stretched link, so a pointer
  // click lands on the text; the keyboard reaches the link itself.
  await page.getByRole("link", { name: `Open details for ${title}` }).press("Enter");
  const dialog = page.getByRole("dialog", { name: title });
  await expect(dialog).toBeVisible();
  return dialog;
};

const asMember = async (browser: Browser, slug: string) => {
  const context = await browser.newContext({ storageState: stateOf(slug) });
  return { context, page: await context.newPage() };
};

test.use({ storageState: managerState });

test("raising a full session's limit seats the first waiter, and only her", async ({
  page,
  browser,
}, testInfo) => {
  const title = `Harbor Siege ${testInfo.retry + 1}`;
  const first = await asMember(browser, "e2e-tide-first");
  const second = await asMember(browser, "e2e-tide-second");

  for (const member of [first, second]) {
    const dialog = await openSession(member.page, title);
    await expect(dialog.getByText("On the waiting list")).toBeVisible();
  }

  await page.goto(PANEL_URL);
  await page.getByRole("link", { name: title, exact: true }).click();
  await page.getByRole("link", { name: "Edit", exact: true }).click();
  const limit = page.getByRole("spinbutton", { name: "Participants Limit" });
  await expect(limit).toHaveValue("1");
  await limit.fill("2");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("heading", { name: title, level: 2 })).toBeVisible();
  await expect(page.getByRole("definition").filter({ hasText: /^\s*2\s*$/ })).toBeVisible();

  // The first in the queue holds the new seat without lifting a finger.
  const seated = await openSession(first.page, title);
  await expect(seated.getByText("You're enrolled")).toBeVisible();
  await expect(seated.getByRole("button", { name: "Cancel", exact: true })).toBeVisible();
  // The open modal covers the navbar, so the bell is read from another page.
  await first.page.goto("/");
  await first.page.getByRole("button", { name: /Notifications/ }).click();
  await expect(
    first.page
      .locator("#navbar-notifications-panel")
      .getByRole("link", { name: new RegExp(title) }),
  ).toBeVisible();

  // One seat opened, so the second in the queue keeps waiting.
  const waiting = await openSession(second.page, title);
  await expect(waiting.getByText("On the waiting list")).toBeVisible();
  await waiting.getByRole("tab", { name: /Participants/ }).click();
  const roster = waiting.getByRole("tabpanel");
  await expect(roster).toHaveText(
    /Enrolled \(2\/2\)[\s\S]*Ilse First[\s\S]*Waiting List[\s\S]*Otto Second/,
  );

  await attachArtifacts(testInfo, {
    name: "capacity-promotion",
    region: waiting,
    facts: { session: title, limit: 2, promoted: "Ilse First", stillWaiting: "Otto Second" },
  });
  await first.context.close();
  await second.context.close();
});
