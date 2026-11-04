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
// NOTE: "Solo Encore" is presented by a user who browses in Polish (bootstrap_data.py).
const proposerState = path.join(__dirname, "..", ".auth-state-polish-proposer.json");

async function expectCoverShown(cover: import("@playwright/test").Locator) {
  await expect(cover).toBeVisible();
  await expect(cover).not.toHaveJSProperty("naturalWidth", 0);
}

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
    // The proposer has browsed in Polish before; the organizer accepts in English.
    const proposer = await browser.newContext({ storageState: proposerState, locale: "pl-PL" });
    const proposerPage = await proposer.newPage();
    await proposerPage.goto(`/event/${EVENT}/`);

    const decision = await reviewProposal(page, "Solo Encore");
    // The organizer judges the proposal with the cover it will be shown with.
    await expectCoverShown(page.locator("[data-session-cover]"));
    const [namedRoom, namedSlot] = await decision.locator("dd").allInnerTexts();

    await decision.getByRole("button", { name: "Accept and add to agenda" }).click();
    await expect(page).toHaveURL(new RegExp(`/event/${EVENT}/$`));

    // A hidden value nobody saw could schedule somewhere else, so the booking
    // has to read back as the room and the hours the card named.
    await page.getByRole("link", { name: "Open details for Solo Encore" }).click();
    const details = page.getByRole("dialog");
    await expect(details).toContainText(namedRoom.trim());
    const modalCover = details.locator("[data-session-cover]");
    await expectCoverShown(modalCover);
    const box = (await modalCover.boundingBox())!;
    expect(box.width / box.height).toBeCloseTo(16 / 9, 1);
    const [start, end] = namedSlot.trim().split("–");
    await expect(details).toContainText(`${start.slice(-5)}–${end}`);

    // The proposer hears about it in the bell, in their language, and the
    // link opens the session.
    await proposerPage.reload();
    await proposerPage.getByRole("button", { name: /Powiadomienia/ }).click();
    const panel = proposerPage.locator("#navbar-notifications-panel");
    const notification = panel.getByRole("link", { name: /Zaakceptowano: Solo Encore/ });
    await expect(notification).toContainText(
      "Twoje zgłoszenie na Solo Room Convention zostało zaakceptowane i dodane do programu.",
    );
    await attachArtifacts(test.info(), {
      name: "proposal-accepted-notification",
      region: panel,
      facts: { title: "Zaakceptowano: Solo Encore", event: EVENT, language: "pl" },
    });
    await notification.click();
    await expect(proposerPage).toHaveURL(new RegExp(`/event/${EVENT}/\\?session=\\d+$`));
    await expect(proposerPage.getByRole("dialog")).toContainText("Solo Encore");
    await proposer.close();
  });

  test("with its one placement taken, the page says so instead of offering it", async ({
    page,
  }) => {
    // Runs after Solo Encore took the only room in the only slot.
    const decision = await reviewProposal(page, "Solo Showcase");
    await expect(decision.getByText(/Every space is taken at every time/)).toBeVisible();
    await expect(decision.getByRole("button", { name: "Accept and add to agenda" })).toHaveCount(0);
    await expect(decision.getByRole("link", { name: "Add a space" })).toBeVisible();
  });
});

test.describe("Accepting into a partly booked slot", () => {
  test.use({ storageState: managerState });

  test("a room already held then is shown taken, not offered", async ({ page }) => {
    await page.goto("/event/accept-crowded-1/");
    await page.getByRole("link", { name: "Review proposal Crowded Pitch" }).click();
    const space = page.getByRole("combobox", { name: "Space" });

    await expect(space.getByRole("option", { name: "Booked Room · taken" })).toBeDisabled();
    await expect(space.getByRole("option", { name: "North Room" })).toBeEnabled();
    await expect(space.getByRole("option", { name: "South Room" })).toBeEnabled();
    // The rejection this used to end in has nothing left to reject.
    await expect(page.getByText("There is already a session scheduled")).toHaveCount(0);
    await attachArtifacts(test.info(), {
      name: "accept-taken-room",
      region: page.getByRole("heading", { name: "Schedule it" }).locator(".."),
      facts: { taken: ["Booked Room"], free: ["North Room", "South Room"] },
    });
  });

  test("with the time open too, the room follows the time picked", async ({ page }) => {
    await page.goto("/event/accept-crowded-2/");
    await page.getByRole("link", { name: "Review proposal Crowded Pitch" }).click();
    const slot = page.getByRole("combobox", { name: "Time slot" });
    const space = page.getByRole("combobox", { name: "Space" });
    const [first, second] = await slot
      .getByRole("option")
      .filter({ hasNotText: "Choose a time" })
      .evaluateAll((options) => options.map((option) => (option as HTMLOptionElement).value));

    await space.selectOption({ label: "Booked Room" });
    await slot.selectOption(first);
    await expect(space.getByRole("option", { name: "Booked Room · taken" })).toBeDisabled();
    // A pick the new time rules out is dropped, not submitted.
    await expect(space).toHaveValue("");

    await slot.selectOption(second);
    await expect(space.getByRole("option", { name: "Booked Room", exact: true })).toBeEnabled();
    await attachArtifacts(test.info(), {
      name: "accept-room-follows-time",
      region: page.getByRole("heading", { name: "Schedule it" }).locator(".."),
      facts: { takenInFirstSlot: ["Booked Room"], freeInSecondSlot: ["Booked Room"] },
    });
  });
});

test.describe("Accepting into a meetup that needs no room", () => {
  test.use({ storageState: managerState });

  test("it asks only for the time and puts the session on the programme", async ({ page }) => {
    await page.goto("/event/roomless-meetup/");
    await page.getByRole("link", { name: "Review proposal Roomless Talk" }).click();
    const decision = page.getByRole("heading", { name: "Schedule it" }).locator("..");

    // No space to choose, and none required: the card names only the time.
    await expect(decision.getByRole("combobox")).toHaveCount(0);
    await expect(decision.getByText("Time slot", { exact: true })).toBeVisible();
    await decision.getByRole("button", { name: "Accept and add to agenda" }).click();
    await expect(page).toHaveURL(/\/event\/roomless-meetup\/$/);

    const card = page.locator("[data-session-card]").filter({ hasText: "Roomless Talk" });
    await expect(card).toBeVisible();
    await attachArtifacts(test.info(), {
      name: "roomless-meetup-card",
      region: card,
      facts: { session: "Roomless Talk", space: null },
    });
    await page.getByRole("link", { name: "Open details for Roomless Talk" }).click();
    await expect(page.getByRole("dialog", { name: "Roomless Talk" })).toBeVisible();
  });
});
