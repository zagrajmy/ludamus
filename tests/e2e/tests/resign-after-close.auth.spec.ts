import { expect, test } from "./helpers/fixtures";

// The seeded e2e-tester holds a confirmed seat on closed-enrollment, an event
// with no enrollment config at all (tests/e2e/scripts/bootstrap_data.py). A
// shut window hides the ways in, never the way out.

test.describe("Resigning after enrollment closes", () => {
  test("enrolled viewer can give the seat back", async ({ page }) => {
    await page.goto("/event/closed-enrollment/");

    await page.getByRole("link", { name: "Open details for Late Resignation Demo" }).click();

    const dialog = page.getByRole("dialog", { name: "Late Resignation Demo" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("You're enrolled")).toBeVisible();

    // Closed enrollment makes this one-way, so the button asks first.
    const cancel = dialog.getByRole("button", { name: "Cancel", exact: true });
    page.once("dialog", (confirmation) => confirmation.accept());
    await cancel.click();

    await expect(cancel).toHaveCount(0);
    await expect(dialog.getByRole("button", { name: "Enroll", exact: true })).toHaveCount(0);
  });
});
