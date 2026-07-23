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

  let openedByHover = false;

  const isOpen = (): boolean => button.getAttribute("aria-expanded") === "true";

  const setOpen = (open: boolean): void => {
    button.setAttribute("aria-expanded", open ? "true" : "false");
    panel.hidden = !open;
  };

  const close = (): void => {
    openedByHover = false;
    setOpen(false);
  };

  setOpen(false);

  button.addEventListener("click", () => {
    const open = openedByHover || !isOpen();
    openedByHover = false;
    setOpen(open);
    if (open) {
      panel.querySelector<HTMLElement>(FOCUSABLE)?.focus();
    }
  });

  if (root.hasAttribute("data-menu-hover")) {
    button.addEventListener("pointerenter", () => {
      if (!HOVER_QUERY.matches || isOpen()) return;
      openedByHover = true;
      setOpen(true);
    });

    root.addEventListener("pointerleave", () => {
      if (HOVER_QUERY.matches && openedByHover) {
        close();
      }
    });

    root.addEventListener("focusin", (event: FocusEvent) => {
      if (isOpen() && panel.contains(event.target as Node)) {
        openedByHover = false;
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
      close();
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
