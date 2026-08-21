import { expect, test } from "./helpers/fixtures";

// The event page's proposal cards. Their Python tests assert context and
// authorization; everything these specs touch is markup, which per
// CLAUDE.md is this suite's job — the card's link target, the slot summary
// that replaced the room, and the superuser mark.
const EVENT_URL = "/event/autumn-open/";

test.describe("Proposal cards", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Username:").fill("e2e-manager");
    await page.getByLabel("Password:").fill("e2e-manager-123");
    await page.getByRole("button", { name: /Log in/i }).click();
  });

  test("shows pending proposals under their own heading", async ({ page }) => {
    await page.goto(EVENT_URL);

    const section = page.locator('[data-time-slot="pending-proposals"]');
    await expect(section).toBeVisible();
    await expect(section.getByText("Proposals to review")).toBeVisible();
    await expect(section.getByRole("heading", { name: "Pending Neon Proposal" })).toBeVisible();
  });

  test("card links to the review screen, not the session modal", async ({ page }) => {
    await page.goto(EVENT_URL);

    const link = page.getByRole("link", {
      name: "Review proposal Pending Neon Proposal",
    });
    await expect(link).toHaveAttribute("href", /\/session\/\d+\/accept\/$/);
  });

  test("states the slot it asks for, as a range", async ({ page }) => {
    await page.goto(EVENT_URL);

    const card = page
      .locator('[data-time-slot="pending-proposals"] .session')
      .filter({ hasText: "Pending Neon Proposal" });
    // A range, never a bare date — that is what makes it read as a slot
    // rather than as a submission stamp.
    await expect(card).toContainText(/\d{1,2}:\d{2}–\d{1,2}:\d{2}/);
    await expect(card).toContainText("4 seats");
  });

  test("a no-sign-up proposal states no seat count", async ({ page }) => {
    await page.goto(EVENT_URL);

    const card = page
      .locator('[data-time-slot="pending-proposals"] .session')
      .filter({ hasText: "Open Table Proposal" });
    // participants_limit 0 means "no enrollment", not a full session.
    await expect(card).not.toContainText("seat");
  });

  test("more slots than fit are named to assistive tech", async ({ page }) => {
    await page.goto(EVENT_URL);

    const card = page
      .locator('[data-time-slot="pending-proposals"] .session')
      .filter({ hasText: "Open Table Proposal" });
    await expect(card).toContainText("+2 more");
    // The visible row has room for one slot; the rest are read out, because a
    // title tooltip cannot fire under the card's pointer-events-none wrapper.
    await expect(card.locator("[data-overflow-slots]")).toContainText("–");
  });

  test("a proposal is not offered to the enrollment filters", async ({ page }) => {
    await page.goto(EVENT_URL);

    // data-status feeds session-filters.ts document-wide. "unavailable" would
    // surface the whole review queue under an enrollment filter.
    const card = page
      .locator('[data-time-slot="pending-proposals"] .session')
      .filter({ hasText: "Pending Neon Proposal" });
    await expect(card).toHaveAttribute("data-status", "proposal");
    await expect(card).toHaveAttribute("data-takes-enrollment", "false");
  });
});
