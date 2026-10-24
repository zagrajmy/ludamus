import { expect, test } from "./helpers/fixtures";
import { settleViewTransitions, supportsViewTransitions } from "./helpers/view-transitions";

for (const newer of ["none", "other", "replacement"] as const) {
  test(`replacing a queued dialog preserves ${newer} newer dialog state`, async ({
    page,
  }, testInfo) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(`${error.name}: ${error.message}`));
    await page.goto("/event/autumn-open/");
    test.skip(!(await supportsViewTransitions(page)), "Requires a deferred view-transition swap");

    const trigger = page.getByRole("link", { name: "Open details for Mega Strategy Lab" });
    const otherTrigger = page.getByRole("link", {
      name: "Open details for Cozy Storytellers Circle",
    });
    const other = page.getByRole("dialog", { name: "Cozy Storytellers Circle" });
    await otherTrigger.press("Enter");
    await expect(other).toBeVisible();
    await settleViewTransitions(page);
    await page.keyboard.press("Escape");
    await expect(other).toBeHidden();
    await settleViewTransitions(page);

    const id = await trigger.getAttribute("aria-controls");
    const otherId = await otherTrigger.getAttribute("aria-controls");
    const href = await trigger.getAttribute("href");
    const otherHref = await otherTrigger.getAttribute("href");
    if (!id || !otherId || !href || !otherHref) throw new Error("Missing addressable dialog");
    const [param, value] = [...new URL(href, page.url()).searchParams][0];
    const newerId = newer === "other" ? otherId : id;
    const newerHref = newer === "other" ? otherHref : href;
    const expectedValue =
      newer === "none" ? null : new URL(newerHref, page.url()).searchParams.get(param);

    const race = await page.evaluateHandle(
      ({ id, newer, newerId, newerHref }) => {
        let resume!: () => void;
        let scheduled!: () => void;
        let stale: HTMLDialogElement | null = null;
        let transition: ViewTransition | null = null;
        const gate = new Promise<void>((resolve) => {
          resume = resolve;
        });
        const queued = new Promise<void>((resolve) => {
          scheduled = resolve;
        });
        const startViewTransition = document.startViewTransition.bind(document);
        document.startViewTransition = (update) => {
          document.startViewTransition = startViewTransition;
          transition = startViewTransition(async () => {
            scheduled();
            await gate;
            if (typeof update === "function") await update();
            else await update?.update?.();
          });
          return transition;
        };
        return {
          queued,
          replaceAndResume: () => {
            const dialog = document.getElementById(id);
            if (!(dialog instanceof HTMLDialogElement)) throw new Error("Missing queued dialog");
            stale = dialog;
            dialog.replaceWith(dialog.cloneNode(true));
            if (newer !== "none") {
              const current = document.getElementById(newerId);
              if (!(current instanceof HTMLDialogElement)) throw new Error("Missing newer dialog");
              current.showModal();
              document
                .querySelector(`[data-session-id="${newerId.slice("session-".length)}"]`)
                ?.classList.add("session-suppressed");
              history.replaceState({}, "", newerHref);
            }
            resume();
          },
          finish: async () => {
            if (!transition) throw new Error("Opening did not schedule a transition");
            return transition.finished.then(
              () => "fulfilled",
              (error: Error) => `${error.name}: ${error.message}`,
            );
          },
          snapshot: () => ({
            staleConnected: stale?.isConnected,
            staleOpen: stale?.open,
            openDialogs: document.querySelectorAll("dialog[open]").length,
            modalSnapshots: [...document.querySelectorAll<HTMLElement>("[style]")]
              .filter((element) => element.style.viewTransitionName === "session-morph")
              .map((element) => element.tagName),
            suppressedCards: document.querySelectorAll(".session-suppressed").length,
            pageLive: document.documentElement.classList.contains("vt-page-live"),
          }),
        };
      },
      { id, newer, newerId, newerHref },
    );

    await trigger.press("Enter", { noWaitAfter: true });
    await race.evaluate(({ queued }) => queued);
    await expect(page).toHaveURL((url) => url.searchParams.get(param) === value);
    await race.evaluate(({ replaceAndResume }) => replaceAndResume());
    expect(await race.evaluate(({ finish }) => finish())).toBe("fulfilled");
    await settleViewTransitions(page);
    const snapshot = await race.evaluate(({ snapshot }) => snapshot());
    await testInfo.attach("detached-dialog-transition", {
      body: JSON.stringify({ id, newer, snapshot, url: page.url(), errors }, null, 2),
      contentType: "application/json",
    });
    expect(snapshot).toEqual({
      staleConnected: false,
      staleOpen: false,
      openDialogs: newer === "none" ? 0 : 1,
      modalSnapshots: [],
      suppressedCards: newer === "none" ? 0 : 1,
      pageLive: false,
    });
    await expect(page).toHaveURL((url) => url.searchParams.get(param) === expectedValue);
    expect(errors).toEqual([]);

    if (newer !== "none") {
      await expect(page.getByRole("dialog")).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(page.getByRole("dialog")).toHaveCount(0);
      await settleViewTransitions(page);
    }

    await otherTrigger.press("Enter");
    await expect(other).toBeVisible();
    await settleViewTransitions(page);
    await page.keyboard.press("Escape");
    await expect(other).toBeHidden();
    await settleViewTransitions(page);

    await trigger.press("Enter");
    await expect(page.getByRole("dialog", { name: "Mega Strategy Lab" })).toBeVisible();
    await settleViewTransitions(page);
    expect(errors).toEqual([]);
    const screenshot = testInfo.outputPath("recovered-dialog.png");
    await page.screenshot({ path: screenshot, fullPage: true });
    await testInfo.attach("recovered-dialog", {
      path: screenshot,
      contentType: "image/png",
    });
  });
}

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
