import { expect, test } from "./helpers/fixtures";

// Both events take proposals, have enrollment open and few enough sessions
// for the card grid. A slot header's own propose link only helps when there
// are slots to tell apart; on a one-slot schedule it would repeat the
// section's button right above it.
test.describe("Proposing from a small event", () => {
  test("a single slot leaves the section button as the one way in", async ({ page }) => {
    await page.goto("/event/lone-table/");
    const schedule = page.locator("#schedule-region");

    await expect(schedule.locator(".time-slot-section")).toHaveCount(1);
    await expect(schedule.getByText("Not Yet Available")).toHaveCount(0);
    await expect(schedule.getByRole("link", { name: "Propose Session" })).toBeVisible();
    await expect(schedule.locator('a[href="/event/lone-table/session/propose/"]')).toHaveCount(1);
  });

  test("several slots put a propose link on the slot headers too", async ({ page }) => {
    await page.goto("/event/autumn-open/");
    const schedule = page.locator("#schedule-region");

    await expect(schedule.getByRole("link", { name: "Propose Session" })).toBeVisible();
    await expect(
      schedule
        .locator(".time-slot-section")
        .first()
        .getByRole("link", { name: "Propose", exact: true }),
    ).toBeVisible();
  });
});
