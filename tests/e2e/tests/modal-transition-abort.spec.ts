import { expect, test } from "./helpers/fixtures";
import { settleViewTransitions } from "./helpers/view-transitions";

// Closing a modal while its opening morph is still capturing starts a second
// view transition, which skips the first and rejects its `ready`. Chrome no
// longer marks that rejection handled, so the page has to.
test("closing a modal mid-open leaves no unhandled rejection", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(`${error.name}: ${error.message}`));
  await page.goto("/event/autumn-open/");

  // The observer fires on the microtask right after showModal() inside the
  // opening transition's update callback: always before `ready` can settle.
  await page.evaluate(() => {
    const observer = new MutationObserver((records) => {
      for (const { target } of records) {
        if (target instanceof HTMLDialogElement && target.open) {
          observer.disconnect();
          target.dispatchEvent(new Event("cancel", { cancelable: true }));
          document.documentElement.dataset.closedMidOpen = "";
        }
      }
    });
    observer.observe(document.documentElement, { attributeFilter: ["open"], subtree: true });
  });
  await page.getByRole("link", { name: "Open details for Mega Strategy Lab" }).press("Enter");

  await expect(page.locator("html[data-closed-mid-open]")).toHaveCount(1);
  await expect(page.getByRole("dialog", { name: "Mega Strategy Lab" })).toBeHidden();
  await settleViewTransitions(page);
  expect(errors).toEqual([]);
});
