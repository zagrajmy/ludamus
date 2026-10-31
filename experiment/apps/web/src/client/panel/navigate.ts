import { Effect } from "effect";
import { load } from "foldkit/navigation";

import type { FlashLevel } from "../../ui/flash.js";

export const FLASH_COOKIE = "flash";

export type FlashNote = Readonly<{ level: FlashLevel; text: string }>;

const LEAVING = "panelLeaving";

const markLeaving = () => {
  document.documentElement.dataset[LEAVING] = "1";
};

export const watchForLeaving = Effect.sync(() => {
  window.addEventListener("beforeunload", markLeaving, { once: true });
});

const isLeaving = () => document.documentElement.dataset[LEAVING] === "1";

export const navigateWithFlash = (
  href: string,
  notes: readonly FlashNote[]
): Effect.Effect<void> =>
  Effect.suspend(() => {
    if (notes.length > 0) {
      // oxlint-disable-next-line unicorn/no-document-cookie -- the server reads this flash on the next full load; the Cookie Store API is missing from Firefox and WebKit, which the suite also runs.
      document.cookie = `${FLASH_COOKIE}=${encodeURIComponent(JSON.stringify(notes))}; Path=/; SameSite=Lax`;
    }

    return isLeaving() ? Effect.void : load(href);
  });

export const reloadWithFlash = (notes: readonly FlashNote[]) =>
  Effect.suspend(() =>
    navigateWithFlash(
      `${window.location.pathname}${window.location.search}`,
      notes
    )
  );
