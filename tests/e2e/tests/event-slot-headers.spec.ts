import { expect, test } from "./helpers/fixtures";

// slot-states runs from yesterday to tomorrow: one slot is over, and
// tomorrow's 10:00 holds a sign-up-free talk beside a workshop whose window
// has not opened, ahead of a sign-up-free 14:00. Enrollment is each card's
// to state, so the headings are times alone, one per start, in time order.
test.describe("Card schedule slot headings", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/event/slot-states/");
  });

  test("tomorrow reads one heading per start time, in time order", async ({ page }) => {
    const slots = page
      .locator("#schedule-region [data-schedule-day]")
      .last()
      .locator(".time-slot-section");

    await expect(slots).toHaveCount(2);
    await expect(slots.nth(0)).toContainText("10:00");
    await expect(slots.nth(0)).toContainText("Now");
    await expect(slots.nth(0)).toContainText("Welcome Talk");
    await expect(slots.nth(0)).toContainText("Dice Workshop");
    await expect(slots.nth(1)).toContainText("14:00");
    await expect(slots.nth(1)).toContainText("Closing Circle");
  });

  test("headings carry no status words, and only the finished slot greys out", async ({ page }) => {
    const schedule = page.locator("#schedule-region");

    await expect(schedule.getByText("Not Yet Available")).toHaveCount(0);
    await expect(schedule.getByText("Completed")).toHaveCount(0);
    const ended = schedule.locator(".time-slot-section[data-ended]");
    await expect(ended).toHaveCount(1);
    await expect(ended).toContainText("Low Tide Skirmish");
  });
});
