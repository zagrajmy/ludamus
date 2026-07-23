// Accessible disclosure menus: click/keyboard operable with a live
// aria-expanded, Esc to close, and click-outside to dismiss. Menus opting into
// data-menu-hover also open on hover-capable devices; their markup bridges the
// trigger-to-panel gap with a safe pointer corridor.

const FOCUSABLE = 'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])';
const HOVER_QUERY = globalThis.matchMedia("(hover: hover)");

const init = (root: HTMLElement): void => {
  const button = root.querySelector<HTMLElement>("[data-menu-button]");
  const panel = root.querySelector<HTMLElement>("[data-menu-panel]");
  if (!button || !panel) return;

  const surface = panel.querySelector<HTMLElement>("[data-menu-surface]");
  const isOpen = (): boolean => button.getAttribute("aria-expanded") === "true";

  const setOpen = (open: boolean, animate = false): void => {
    button.setAttribute("aria-expanded", open ? "true" : "false");
    if (!surface) {
      panel.hidden = !open;
      return;
    }

    if (open) {
      panel.hidden = false;
    }

    if (!animate) {
      surface.style.transitionDuration = "0ms";
    } else if (open) {
      void surface.offsetWidth;
    }

    surface.toggleAttribute("data-menu-visible", open);

    if (!animate) {
      panel.hidden = !open;
      requestAnimationFrame(() => surface.style.removeProperty("transition-duration"));
    } else if (!open) {
      surface.addEventListener(
        "transitionend",
        () => {
          if (!isOpen()) panel.hidden = true;
        },
        { once: true },
      );
    }
  };

  const close = (animate = false): void => setOpen(false, animate);

  setOpen(false);

  button.addEventListener("click", (event: MouseEvent) => {
    const open = !isOpen();
    setOpen(open, event.detail > 0);
    if (open) {
      panel.querySelector<HTMLElement>(FOCUSABLE)?.focus();
    }
  });

  if (root.hasAttribute("data-menu-hover")) {
    button.addEventListener("pointerenter", () => {
      if (!HOVER_QUERY.matches || isOpen()) return;
      setOpen(true, true);
    });

    root.addEventListener("pointerleave", () => {
      if (HOVER_QUERY.matches && isOpen()) {
        close(true);
      }
    });
  }

  root.addEventListener("keydown", (event: KeyboardEvent) => {
    if (event.key === "Escape" && isOpen()) {
      close();
      button.focus();
    }
  });

  document.addEventListener("click", (event: MouseEvent) => {
    if (isOpen() && !root.contains(event.target as Node)) {
      close(event.detail > 0);
    }
  });

  document.addEventListener("focusin", (event: FocusEvent) => {
    if (isOpen() && !root.contains(event.target as Node)) {
      close();
    }
  });
};

const wire = (): void => {
  for (const root of document.querySelectorAll<HTMLElement>("[data-menu]")) {
    init(root);
  }
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", wire);
} else {
  wire();
}
