import { type Page } from "@playwright/test";

// Chromium/Firefox only: WebKit does not expose ::view-transition pseudo-element
// animations to document.getAnimations(), so this resolves immediately there
// rather than actually waiting for the morph. Don't read a WebKit pass as
// evidence the transition settled.
//
// A single "no ::view-transition animations right now" check races a real
// transition on both ends: right after the trigger, the pseudo-elements have
// not been created yet (they land on a later frame), so the first check can
// read "settled" before the morph even starts; between two staged
// transitions (e.g. the dialog opening, then the footer morphing into its
// compact form), the gap where neither is animating reads the same way.
// Require two consecutive clear animation frames before calling it settled,
// so a not-yet-started or about-to-start transition can't slip through.
export const settleViewTransitions = (page: Page): Promise<void> =>
  page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        const isTransitioning = () =>
          document
            .getAnimations()
            .some((a) =>
              (a.effect as KeyframeEffect | null)?.pseudoElement?.startsWith("::view-transition"),
            );
        let clearFrames = 0;
        const tick = () => {
          clearFrames = isTransitioning() ? 0 : clearFrames + 1;
          if (clearFrames >= 2) {
            resolve();
            return;
          }
          requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      }),
  );

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
