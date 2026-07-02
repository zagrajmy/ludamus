// Flash messages (Django `messages`). The markup carries the full intent —
// `data-flash="sticky|transient"`, a `[data-flash-dismiss]` button, and
// role/aria-live — but nothing implemented it. This wires that up: every flash
// is dismissible, and transient ones auto-dismiss after a pause-able delay.
// Exits are reduced-motion-safe.

const AUTO_DISMISS_MS = 5000;
const EXIT_MS = 200;

const prefersReducedMotion = (): boolean =>
  globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

const remove = (flash: HTMLElement): void => {
  if (flash.dataset.flashClosing === "true") return;
  flash.dataset.flashClosing = "true";

  if (prefersReducedMotion()) {
    flash.remove();
    return;
  }

  const animation = flash.animate(
    [
      { opacity: 1, transform: "translateY(0)" },
      { opacity: 0, transform: "translateY(-0.25rem)" },
    ],
    // Strong ease-out: starts fast so the message reads as leaving immediately.
    { duration: EXIT_MS, easing: "cubic-bezier(0.3, 0, 0, 1)", fill: "forwards" },
  );
  void animation.finished.finally(() => {
    flash.remove();
  });
};

const init = (flash: HTMLElement): void => {
  const dismiss = flash.querySelector<HTMLElement>("[data-flash-dismiss]");
  dismiss?.addEventListener("click", () => {
    remove(flash);
  });

  if (flash.dataset.flash !== "transient") return;

  let timer: ReturnType<typeof setTimeout> | undefined;
  const start = (): void => {
    timer = setTimeout(() => {
      remove(flash);
    }, AUTO_DISMISS_MS);
  };
  const pause = (): void => {
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
  };

  // Don't yank a message out from under someone who's reading or interacting.
  flash.addEventListener("pointerenter", pause);
  flash.addEventListener("focusin", pause);
  flash.addEventListener("pointerleave", start);
  flash.addEventListener("focusout", start);

  start();
};

const wire = (): void => {
  for (const flash of document.querySelectorAll<HTMLElement>("[data-flash]")) {
    init(flash);
  }
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", wire);
} else {
  wire();
}
