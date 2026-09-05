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
