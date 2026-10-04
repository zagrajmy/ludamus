import { expect, test } from "./helpers/fixtures";

// slot-states runs from yesterday to tomorrow: one slot is over, and
// tomorrow's 10:00 holds a sign-up-free talk beside a workshop whose window
// has not opened, ahead of a sign-up-free 14:00. Enrollment is each card's
// to state, so each slot is a group named by its time alone, one per start,
// in time order. Yesterday's day is folded, so only tomorrow's groups show.
const timeSlot = /\d{2}:\d{2}$/;

test.describe("Card schedule slot groups", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/event/slot-states/");
  });

  test("the open day reads one group per start time, in time order", async ({ page }) => {
    const slots = page.getByRole("group", { name: timeSlot });

    await expect(slots).toHaveCount(2);
    await expect(slots.nth(0)).toHaveAccessibleName("10:00");
    await expect(slots.nth(0)).toContainText("Now");
    await expect(slots.nth(0)).toContainText("Welcome Talk");
    await expect(slots.nth(0)).toContainText("Dice Workshop");
    await expect(slots.nth(1)).toHaveAccessibleName("14:00");
    await expect(slots.nth(1)).toContainText("Closing Circle");
  });

  test("the finished slot says so on its card, and no heading carries a status", async ({
    page,
  }) => {
    const finished = page.getByRole("group", { name: "18:00", includeHidden: true });

    await expect(finished).toContainText("Low Tide Skirmish");
    await expect(finished).toContainText("Ended");
    await expect(page.getByRole("main").getByText(/Not Yet Available|Completed/)).toHaveCount(0);
  });
});
