import { expect, test } from "./helpers/fixtures";

// accept-lab is seeded with one bookable room and one time slot, so the
// scheduling form has nothing to ask. The organizer still has to be told
// where and when they are about to put the session.
const EVENT = "accept-lab";
const PROPOSAL = "Solo Showcase";

test.describe("Accepting a proposal", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Username:").fill("e2e-manager");
    await page.getByLabel("Password:").fill("e2e-manager-123");
    await page.getByRole("button", { name: /Log in/i }).click();
    await page.goto(`/event/${EVENT}/`);
    await page.getByRole("link", { name: `Review proposal ${PROPOSAL}` }).click();
  });

  test("a foregone space and time are named, not asked for", async ({ page }) => {
    await expect(page.getByRole("heading", { name: "Schedule it" })).toBeVisible();

    // Nothing to choose, so nothing asks.
    await expect(page.getByRole("combobox")).toHaveCount(0);

    // The decision card names what the button is about to commit to.
    const decision = page.getByRole("heading", { name: "Schedule it" }).locator("..");
    await expect(decision.getByText("The Only Room")).toBeVisible();
    await expect(decision.getByText("Space", { exact: true })).toBeVisible();
    await expect(decision.getByText("Time slot", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Accept and add to agenda" })).toBeVisible();
  });

  test("the room and time it names are the ones it submits", async ({ page }) => {
    const named = await page
      .getByRole("heading", { name: "Schedule it" })
      .locator("..")
      .locator("dd")
      .allInnerTexts();

    await page.getByRole("button", { name: "Accept and add to agenda" }).click();

    // The agenda entry the accept created carries the same room and time the
    // page named — a hidden value nobody saw would schedule somewhere else.
    await expect(page).toHaveURL(new RegExp(`/event/${EVENT}/$`));
    const agenda = page.locator(".session", { hasText: PROPOSAL }).first();
    await expect(agenda).toBeVisible();
    await expect(agenda).toContainText("The Only Room");
    expect(named.map((text) => text.trim())).toContain("The Only Room");
  });
});
