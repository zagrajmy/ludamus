import { type Page } from "@playwright/test";

// Chromium/Firefox only: WebKit does not expose ::view-transition pseudo-element
// animations to document.getAnimations(), so this resolves immediately there
// rather than actually waiting for the morph. Don't read a WebKit pass as
// evidence the transition settled.
export const settleViewTransitions = (page: Page): Promise<void> =>
  page
    .waitForFunction(
      () =>
        !document
          .getAnimations()
          .some((a) =>
            (a.effect as KeyframeEffect | null)?.pseudoElement?.startsWith("::view-transition"),
          ),
    )
    .then(() => undefined);

// Counts document.startViewTransition calls. WebKit does not expose the
// transition's animations to getAnimations(), so the call itself is the
// evidence a transition ran (or did not). Install before the first goto.
const COUNTER = "__viewTransitionsStarted";

export const trackViewTransitions = async (page: Page): Promise<void> => {
  await page.addInitScript((key: string) => {
    const counters = globalThis as unknown as Record<string, number>;
    counters[key] = 0;
    const proto = Document.prototype as unknown as {
      startViewTransition?: (callback: () => void) => unknown;
    };
    const original = proto.startViewTransition;
    if (!original) return;
    proto.startViewTransition = function (this: Document, callback: () => void) {
      counters[key] += 1;
      return original.call(this, callback);
    };
  }, COUNTER);
};

export const viewTransitionsStarted = (page: Page): Promise<number> =>
  page.evaluate((key: string) => (globalThis as unknown as Record<string, number>)[key], COUNTER);

export const supportsViewTransitions = (page: Page): Promise<boolean> =>
  page.evaluate(() => typeof document.startViewTransition === "function");
