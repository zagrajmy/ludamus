import { expect, test } from "./helpers/fixtures";

// Both events take proposals, have enrollment open and few enough sessions
// for the card grid. A slot's own propose link only helps when there are
// slots to tell apart; on a one-slot schedule it would repeat the section's
// button right above it.
const timeSlot = /\d{2}:\d{2}$/;

test.describe("Proposing from a small event", () => {
  test("a single slot leaves the section button as the one way in", async ({ page }) => {
    await page.goto("/event/lone-table/");
    const slots = page.getByRole("group", { name: timeSlot });

    await expect(slots).toHaveCount(1);
    await expect(page.getByRole("link", { name: "Propose Session" })).toBeVisible();
    await expect(slots.getByRole("link", { name: "Propose", exact: true })).toHaveCount(0);
  });

  test("several slots put a propose link on each slot too", async ({ page }) => {
    await page.goto("/event/autumn-open/");
    const slots = page.getByRole("group", { name: timeSlot });

    await expect(page.getByRole("link", { name: "Propose Session" })).toBeVisible();
    await expect(slots.first().getByRole("link", { name: "Propose", exact: true })).toBeVisible();
  });
});
