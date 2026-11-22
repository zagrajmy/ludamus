import { type ReactNode, useEffect, useId, useRef } from "react";

import { Icon } from "./icons";
import { type Panel, PANEL_ID, useBoardUi } from "./ui";

// One panel at a time, floating just above the toolbar it came from. The
// bar stays in view, so on a phone the three controls switch between their
// sheets like tabs; on a wider screen tldraw's menus keep the corners.
export function Sheet({
  children,
  panel,
  title,
}: {
  children: ReactNode;
  panel: Panel;
  title: string;
}) {
  const { copy, open } = useBoardUi();
  const heading = useId();
  const sheet = useRef<HTMLElement>(null);

  // Focus moves in, and goes back to whatever opened the sheet.
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const first = sheet.current?.querySelector<HTMLElement>("[data-autofocus]");
    (first ?? sheet.current?.querySelector<HTMLElement>("h2"))?.focus({ preventScroll: true });
    return () => {
      if (opener?.isConnected) opener.focus({ preventScroll: true });
    };
  }, []);

  // Escape closes the sheet wherever focus is, even on the canvas.
  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) open(null);
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [open]);

  return (
    <>
      <div
        aria-hidden="true"
        className="fixed inset-x-0 top-0 bottom-[calc(3.75rem+env(safe-area-inset-bottom))] z-40 bg-warm-900/20 sm:hidden"
        onClick={() => open(null)}
      />
      <section
        aria-labelledby={heading}
        className="fixed inset-x-2 bottom-[calc(3.75rem+env(safe-area-inset-bottom))] z-50 flex max-h-[min(70dvh,36rem)] flex-col rounded-2xl bg-bg-secondary text-foreground shadow-[0_8px_32px_rgb(37_34_32/0.22)] ring-1 ring-border sm:inset-x-auto sm:bottom-20 sm:left-1/2 sm:max-h-[calc(100dvh-7rem)] sm:w-88 sm:-translate-x-1/2"
        id={PANEL_ID[panel]}
        ref={sheet}
        role="dialog"
      >
        <header className="flex items-center gap-2 py-1 pr-1 pl-4">
          <h2 className="flex-1 text-lg font-semibold outline-none" id={heading} tabIndex={-1}>
            {title}
          </h2>
          <button
            aria-label={copy.close}
            className="grid size-11 place-items-center rounded-full text-foreground-secondary hover:bg-bg-tertiary focus-visible:outline-2 focus-visible:outline-border-focus"
            onClick={() => open(null)}
            type="button"
          >
            <Icon name="Close" />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-4">
          {children}
        </div>
      </section>
    </>
  );
}
