// Accessible disclosure menu for the navbar dropdowns (notifications + profile).
// Click/keyboard operable with a live aria-expanded, Esc to close, and
// click-outside to dismiss — replacing the previous hover/focus-within-only
// reveal so the menus are usable without a pointer and are axe-clean.

const FOCUSABLE =
  'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])';

const init = (root: HTMLElement): void => {
  const button = root.querySelector<HTMLElement>("[data-menu-button]");
  const panel = root.querySelector<HTMLElement>("[data-menu-panel]");
  if (!button || !panel) return;

  const isOpen = (): boolean => button.getAttribute("aria-expanded") === "true";

  const setOpen = (open: boolean): void => {
    button.setAttribute("aria-expanded", open ? "true" : "false");
    panel.hidden = !open;
  };

  setOpen(false);

  button.addEventListener("click", () => {
    const open = !isOpen();
    setOpen(open);
    if (open) {
      panel.querySelector<HTMLElement>(FOCUSABLE)?.focus();
    }
  });

  root.addEventListener("keydown", (event: KeyboardEvent) => {
    if (event.key === "Escape" && isOpen()) {
      setOpen(false);
      button.focus();
    }
  });

  document.addEventListener("click", (event: MouseEvent) => {
    if (isOpen() && !root.contains(event.target as Node)) {
      setOpen(false);
    }
  });

  document.addEventListener("focusin", (event: FocusEvent) => {
    if (isOpen() && !root.contains(event.target as Node)) {
      setOpen(false);
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
