import { managerState } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

// The event page's proposal cards. Their Python tests assert context and
// authorization; everything these specs touch is markup, which per
// CLAUDE.md is this suite's job — the card's link target, the days the
// facilitator offered in place of a room, and the superuser mark.
const EVENT_URL = "/event/autumn-open/";

function proposalCard(page: import("@playwright/test").Page, title: string) {
  return page
    .getByRole("region", { name: "Proposals to review" })
    .getByRole("article")
    .filter({ has: page.getByRole("heading", { name: title }) });
}

test.describe("Proposal cards", () => {
  test.use({ storageState: managerState });

  test("shows pending proposals under their own heading", async ({ page }) => {
    await page.goto(EVENT_URL);

    const section = page.getByRole("region", { name: "Proposals to review" });
    await expect(section).toBeVisible();
    await expect(section.getByRole("heading", { name: "Pending Neon Proposal" })).toBeVisible();
  });

  test("card links to the review screen, not the session modal", async ({ page }) => {
    await page.goto(EVENT_URL);

    const link = page.getByRole("link", {
      name: "Review proposal Pending Neon Proposal",
    });
    await expect(link).toHaveAttribute("href", /\/session\/\d+\/accept\/$/);
  });

  test("states a day it could run on, not a submission stamp", async ({ page }) => {
    await page.goto(EVENT_URL);

    const card = proposalCard(page, "Pending Neon Proposal");
    // A weekday and date: availability is a day now, and naming the weekday
    // is what keeps it from reading as a submission stamp.
    await expect(card).toContainText(/(Mon|Tue|Wed|Thu|Fri|Sat|Sun), \d{1,2} \w+/);
    await expect(card).toContainText("4 seats");
  });

  test("a no-sign-up proposal states no seat count", async ({ page }) => {
    await page.goto(EVENT_URL);

    const card = proposalCard(page, "Open Table Proposal");
    // participants_limit 0 means "no enrollment", not a full session.
    await expect(card).not.toContainText("seat");
  });

  test("more days than fit are named to assistive tech", async ({ page }) => {
    await page.goto(EVENT_URL);

    const card = proposalCard(page, "Open Table Proposal");
    await expect(card).toContainText("+2 more");
    // The visible row has room for one day (a morning); the rest are read
    // out, because a title tooltip cannot fire under the card's
    // pointer-events-none wrapper.
    await expect(card).toContainText("evening");
    await expect(card).toContainText("afternoon");
  });

  test("a proposal is not offered to the enrollment filters", async ({ page }) => {
    await page.goto(EVENT_URL);

    // data-status feeds session-filters.ts document-wide. "unavailable" would
    // surface the whole review queue under an enrollment filter. The
    // attributes are the subject here, so this one reads them directly.
    const filtered = proposalCard(page, "Pending Neon Proposal").locator("[data-status]");
    await expect(filtered).toHaveAttribute("data-status", "proposal");
    await expect(filtered).toHaveAttribute("data-takes-enrollment", "false");
  });
});
