import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";
import { settleViewTransitions, supportsViewTransitions } from "./helpers/view-transitions";

// Closing a modal while its opening morph is still capturing starts a second
// view transition, which skips the first and rejects its `ready`. Chrome no
// longer marks that rejection handled, so the page has to.
test("closing a modal mid-open leaves no unhandled rejection", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(`${error.name}: ${error.message}`));
  await page.goto("/event/autumn-open/");

  // The observer fires on the microtask right after showModal() inside the
  // opening transition's update callback: always before `ready` can settle.
  // Wrapped in an object: evaluateHandle would wait for a bare promise.
  const closedMidOpen = await page.evaluateHandle(() => ({
    done: new Promise<void>((resolve) => {
      const observer = new MutationObserver((records) => {
        for (const { target } of records) {
          if (target instanceof HTMLDialogElement && target.open) {
            observer.disconnect();
            target.dispatchEvent(new Event("cancel", { cancelable: true }));
            resolve();
          }
        }
      });
      observer.observe(document.documentElement, { attributeFilter: ["open"], subtree: true });
    }),
  }));
  await page.getByRole("link", { name: "Open details for Mega Strategy Lab" }).press("Enter");

  await closedMidOpen.evaluate(({ done }) => done);
  await expect(page.getByRole("dialog", { name: "Mega Strategy Lab" })).toBeHidden();
  await settleViewTransitions(page);
  expect(errors).toEqual([]);
});

test("removing a dialog during its opening morph cancels cleanly", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(`${error.name}: ${error.message}`));
  await page.goto("/event/autumn-open/");
  test.skip(!(await supportsViewTransitions(page)), "Requires view transitions");

  const trigger = page.getByRole("link", { name: "Open details for Mega Strategy Lab" });
  const dialog = page.getByRole("dialog", { name: "Mega Strategy Lab", includeHidden: true });
  await trigger.press("Enter");
  await expect(dialog).toBeVisible();
  await settleViewTransitions(page);
  await dialog.getByRole("button", { name: "Close" }).click();
  await expect(dialog).toBeHidden();
  await settleViewTransitions(page);

  const removedMidOpen = await dialog.evaluateHandle((element) => ({
    done: new Promise<void>((resolve) => {
      const observer = new MutationObserver((records) => {
        const morphStarted = records.some(
          ({ target }) =>
            target instanceof HTMLElement &&
            !(target instanceof HTMLDialogElement) &&
            target.style.viewTransitionName === "session-morph",
        );
        if (!morphStarted) return;
        observer.disconnect();
        element.remove();
        resolve();
      });
      observer.observe(document.documentElement, { attributeFilter: ["style"], subtree: true });
    }),
  }));
  await trigger.press("Enter");
  await removedMidOpen.evaluate(({ done }) => done);
  await settleViewTransitions(page);

  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Mega Strategy Lab" })).toBeVisible();
  expect(errors).toEqual([]);

  await trigger.press("Enter");
  await expect(dialog).toBeVisible();
  await settleViewTransitions(page);
  expect(errors).toEqual([]);
  await attachArtifacts(testInfo, {
    name: "modal-after-cancelled-opening",
    region: dialog,
    facts: { uncaughtErrors: errors },
  });
});
