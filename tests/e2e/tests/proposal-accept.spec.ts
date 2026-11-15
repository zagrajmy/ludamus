import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { managerState } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

// accept-lab is seeded with one bookable room, so the space is foregone and the
// card names it rather than asking. The time is a real field now: the organizer
// picks when the session runs. Accepting consumes a pending proposal, so the
// two scenarios run serially against one each.
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

  test("a foregone space is named, and the time is asked for", async ({ page }) => {
    const decision = await reviewProposal(page, "Solo Showcase");

    // One room means no picker; the card names what it will commit to.
    await expect(decision.getByRole("combobox")).toHaveCount(0);
    await expect(decision.getByText("Space", { exact: true })).toBeVisible();
    await expect(decision.getByText(ROOM)).toBeVisible();

    // The time is a genuine choice, so it is a field, pre-filled with the
    // event's opening hour rather than left blank.
    const startsAt = decision.getByLabel("Starts at");
    await expect(startsAt).toBeVisible();
    await expect(startsAt).not.toHaveValue("");
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

  test("the time it is given is the time it books, and the proposer is told", async ({
    browser,
    page,
  }) => {
    // The proposer has browsed in Polish before; the organizer accepts in English.
    const proposer = await browser.newContext({ storageState: proposerState, locale: "pl-PL" });
    const proposerPage = await proposer.newPage();
    await proposerPage.goto(`/event/${EVENT}/`);

    const decision = await reviewProposal(page, "Solo Encore");
    // The organizer judges the proposal with the cover it will be shown with.
    await expectCoverShown(page.locator("[data-session-cover]"));
    const startsAt = decision.getByLabel("Starts at");
    const chosen = (await startsAt.inputValue()).slice(0, 16);

    await decision.getByRole("button", { name: "Accept and add to agenda" }).click();
    await expect(page).toHaveURL(new RegExp(`/event/${EVENT}/$`));

    // A hidden value nobody saw could schedule somewhere else, so the booking
    // has to read back as the room and the hour the form carried.
    await page.getByRole("link", { name: "Open details for Solo Encore" }).click();
    const details = page.getByRole("dialog");
    await expect(details).toContainText(ROOM);
    // The modal leads with the cover as its title's backdrop, whose shape
    // session-modal-cover.spec.ts owns; here it only has to have loaded.
    await expectCoverShown(details.locator("[data-cover-image]"));
    await expect(details).toContainText(chosen.slice(-5));

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
});

// The wall clock the start field holds, moved on by whole hours: read as UTC
// only so that Date adds the hours without the browser's own offset.
function hoursLater(wallClock: string, hours: number): string {
  const at = new Date(`${wallClock.slice(0, 16)}:00Z`);
  at.setUTCHours(at.getUTCHours() + hours);
  return at.toISOString().slice(0, 16);
}

test.describe("Accepting into a partly booked day", () => {
  test.use({ storageState: managerState });

  async function openCrowdedPitch(page: import("@playwright/test").Page) {
    await page.goto("/event/accept-crowded/");
    await page.getByRole("link", { name: "Review proposal Crowded Pitch" }).click();
    return {
      startsAt: page.getByLabel("Starts at"),
      space: page.getByRole("combobox", { name: "Space" }),
    };
  }

  test("a room held at the time picked is shown taken, not offered", async ({ page }) => {
    // The pitch opens at the event's opening and runs into Already Here's hours.
    const { space } = await openCrowdedPitch(page);

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

  test("the room follows the time picked", async ({ page }) => {
    const { startsAt, space } = await openCrowdedPitch(page);
    const opening = await startsAt.inputValue();

    // Three hours on, Already Here has finished, so the room is free again.
    await startsAt.fill(hoursLater(opening, 3));
    const booked = space.getByRole("option", { name: "Booked Room", exact: true });
    await expect(booked).toBeEnabled();
    await space.selectOption({ label: "Booked Room" });

    await startsAt.fill(opening.slice(0, 16));
    await expect(space.getByRole("option", { name: "Booked Room · taken" })).toBeDisabled();
    // A pick the new time rules out is dropped, not submitted.
    await expect(space).toHaveValue("");
    await attachArtifacts(test.info(), {
      name: "accept-room-follows-time",
      region: page.getByRole("heading", { name: "Schedule it" }).locator(".."),
      facts: { takenAtOpening: ["Booked Room"], freeThreeHoursLater: ["Booked Room"] },
    });
  });
});

test.describe("Accepting into a meetup that needs no room", () => {
  test.use({ storageState: managerState });

  test("it asks only for the time and puts the session on the programme", async ({ page }) => {
    await page.goto("/event/roomless-meetup/");
    await page.getByRole("link", { name: "Review proposal Roomless Talk" }).click();
    const decision = page.getByRole("heading", { name: "Schedule it" }).locator("..");

    // No space to choose, and none required: the card asks only for the time.
    await expect(decision.getByRole("combobox")).toHaveCount(0);
    await expect(decision.getByLabel("Starts at")).toBeVisible();
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

    // With no room to give it a column, the timetable still prints it.
    await page.goto("/event/roomless-meetup/print/?material=timetable");
    const sheet = page.getByRole("region", { name: "Print preview" }).getByRole("group");
    await expect(sheet.getByText("No space", { exact: true })).toBeVisible();
    await expect(sheet.getByRole("article", { name: "Roomless Talk" })).toBeVisible();
    await attachArtifacts(test.info(), {
      name: "roomless-meetup-timetable",
      region: sheet,
      facts: { session: "Roomless Talk", column: "No space" },
    });
  });
});
