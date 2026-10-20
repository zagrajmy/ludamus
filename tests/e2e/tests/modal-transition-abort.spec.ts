import { expect, test } from "./helpers/fixtures";

// Closing a modal while its opening morph is still capturing starts a second
// view transition, which skips the first and rejects its `ready`. Chrome no
// longer marks that rejection handled, so the page has to.
test("closing a modal mid-open leaves no unhandled rejection", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(`${error.name}: ${error.message}`));
  await page.goto("/event/autumn-open/");

  const open = page.getByRole("link", { name: "Open details for Mega Strategy Lab" });
  const dialog = page.getByRole("dialog", { name: "Mega Strategy Lab" });
  for (let round = 0; round < 3; round += 1) {
    await open.press("Enter");
    await dialog.press("Escape");
    await expect(dialog).toBeHidden();
  }

  expect(errors).toEqual([]);
});
