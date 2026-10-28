import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { managerState } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

// accept-lab is seeded with one bookable room and one time slot, so the
// scheduling form has nothing to ask. The organizer still has to be told
// where and when they are about to put the session. Accepting consumes a
// pending proposal, so the two scenarios run serially against one each.
test.describe.configure({ mode: "serial" });

const EVENT = "accept-lab";
const ROOM = "The Only Room";
// NOTE: both proposals are presented by the default e2e-tester (bootstrap_data.py).
const proposerState = path.join(__dirname, "..", ".auth-state.json");

async function reviewProposal(page: import("@playwright/test").Page, title: string) {
  await page.goto(`/event/${EVENT}/`);
  await page.getByRole("link", { name: `Review proposal ${title}` }).click();
  return page.getByRole("heading", { name: "Schedule it" }).locator("..");
}

test.describe("Accepting a proposal", () => {
  test.use({ storageState: managerState });

  test("a foregone space and time are named, not asked for", async ({ page }) => {
    const decision = await reviewProposal(page, "Solo Showcase");

    // Nothing to choose, so the decision card asks nothing.
    await expect(decision.getByRole("combobox")).toHaveCount(0);

    // It names what the button is about to commit to instead.
    await expect(decision.getByText("Space", { exact: true })).toBeVisible();
    await expect(decision.getByText(ROOM)).toBeVisible();
    await expect(decision.getByText("Time slot", { exact: true })).toBeVisible();
    await expect(decision.getByRole("button", { name: "Accept and add to agenda" })).toBeVisible();
  });

  test("the decision card stays clear of the sticky navbar", async ({ page }) => {
    // Short enough that the proposal column scrolls past the card, which then
    // pins itself under the navbar instead of sliding beneath it.
    await page.setViewportSize({ width: 1280, height: 480 });
    const card = (await reviewProposal(page, "Solo Showcase")).locator("..");

    // The document never scrolls; #app-scroll owns the scroll (see base.html).
    const scroller = page.locator("#app-scroll");
    // Far enough for the card to pin, short of the grid's end pushing it back up.
    await scroller.evaluate((el) => el.scrollTo(0, 150));
    await expect.poll(() => scroller.evaluate((el) => el.scrollTop)).toBe(150);

    const navBottom = await page
      .locator("nav")
      .first()
      .evaluate((el) => el.getBoundingClientRect().bottom);
    const cardTop = await card.evaluate((el) => el.getBoundingClientRect().top);
    expect(cardTop).toBeGreaterThanOrEqual(navBottom);
  });

  test("the room and time it names are the ones it submits", async ({ browser, page }) => {
    const decision = await reviewProposal(page, "Solo Encore");
    const [namedRoom, namedSlot] = await decision.locator("dd").allInnerTexts();

    await decision.getByRole("button", { name: "Accept and add to agenda" }).click();
    await expect(page).toHaveURL(new RegExp(`/event/${EVENT}/$`));

    // A hidden value nobody saw could schedule somewhere else, so the booking
    // has to read back as the room and the hours the card named.
    await page.getByRole("link", { name: "Open details for Solo Encore" }).click();
    const details = page.getByRole("dialog");
    await expect(details).toContainText(namedRoom.trim());
    const [start, end] = namedSlot.trim().split("–");
    await expect(details).toContainText(`${start.slice(-5)}–${end}`);

    // The proposer hears about it in the bell, and the link opens the session.
    const proposer = await browser.newContext({ storageState: proposerState });
    const proposerPage = await proposer.newPage();
    await proposerPage.goto(`/event/${EVENT}/`);
    await proposerPage.getByRole("button", { name: /Notifications/ }).click();
    const panel = proposerPage.locator("#navbar-notifications-panel");
    const notification = panel.getByRole("link", { name: /Accepted: Solo Encore/ });
    await expect(notification).toContainText(
      "Your proposal for Solo Room Convention was accepted and added to the agenda.",
    );
    await attachArtifacts(test.info(), {
      name: "proposal-accepted-notification",
      region: panel,
      facts: { title: "Accepted: Solo Encore", event: EVENT },
    });
    await notification.click();
    await expect(proposerPage).toHaveURL(new RegExp(`/event/${EVENT}/\\?session=\\d+$`));
    await expect(proposerPage.getByRole("dialog")).toContainText("Solo Encore");
    await proposer.close();
  });
});
