// Accessible disclosure menus: click/keyboard operable with a live
// aria-expanded, Esc to close, and click-outside to dismiss. Menus opting into
// data-menu-hover also open on hover-capable devices; their markup bridges the
// trigger-to-panel gap with a safe pointer corridor.

const FOCUSABLE = 'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])';
const HOVER_QUERY = globalThis.matchMedia("(hover: hover)");
const wired = new WeakSet<HTMLElement>();

// NOTE: a panel sits `absolute` under its trigger, so a rounded card that hides
// its overflow cuts off whatever reaches past its edge: on a phone, a list's
// last "⋯" menu loses its bottom items. Such a panel moves to the top layer as a
// popover, pinned at the spot it already occupies, so neither the card's
// clipping nor a stacking context around it can cover it. It lifts above the
// trigger when it would run past the bottom of the screen. The inline styles
// undo the browser's default popover border, padding and background.
const clippedBy = (panel: HTMLElement): boolean => {
  const box = panel.getBoundingClientRect();
  for (let node = panel.parentElement; node; node = node.parentElement) {
    const { overflowX, overflowY } = getComputedStyle(node);
    if (![overflowX, overflowY].some((value) => value === "hidden" || value === "clip")) continue;
    const edge = node.getBoundingClientRect();
    if (
      box.bottom > edge.bottom ||
      box.top < edge.top ||
      box.right > edge.right ||
      box.left < edge.left
    ) {
      return true;
    }
  }
  return false;
};

const pin = (panel: HTMLElement, button: HTMLElement): void => {
  const box = panel.getBoundingClientRect();
  const trigger = button.getBoundingClientRect();
  const top = box.bottom > window.innerHeight ? Math.max(0, trigger.top - box.height) : box.top;
  const { padding } = getComputedStyle(panel);
  const pinned: Record<string, string> = {
    background: "transparent",
    border: "0",
    color: "inherit",
    inset: "auto",
    left: `${box.left}px`,
    margin: "0",
    overflow: "visible",
    padding,
    position: "fixed",
    top: `${top}px`,
    translate: "none",
    width: `${box.width}px`,
  };
  Object.assign(panel.style, pinned);
  panel.dataset.menuPinned = Object.keys(pinned).join(" ");
  if ("showPopover" in panel) {
    panel.popover = "manual";
    panel.showPopover();
  }
};

const isPinned = (panel: HTMLElement): boolean => panel.dataset.menuPinned !== undefined;

const unpin = (panel: HTMLElement): void => {
  if (panel.hasAttribute("popover")) {
    if (panel.matches(":popover-open")) panel.hidePopover();
    panel.removeAttribute("popover");
  }
  for (const prop of panel.dataset.menuPinned?.split(" ") ?? []) {
    panel.style.removeProperty(prop);
  }
  delete panel.dataset.menuPinned;
};

const init = (root: HTMLElement): void => {
  if (wired.has(root)) return;
  wired.add(root);
  const button = root.querySelector<HTMLElement>("[data-menu-button]");
  const panel = root.querySelector<HTMLElement>("[data-menu-panel]");
  const surface = panel?.querySelector<HTMLElement>("[data-menu-surface]");
  if (!button || !panel || !surface) return;
  const isOpen = (): boolean => button.getAttribute("aria-expanded") === "true";

  const setOpen = (open: boolean, animate = false): void => {
    button.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) {
      panel.hidden = false;
      unpin(panel);
      if (clippedBy(panel)) pin(panel, button);
    }

    if (animate) {
      surface.style.removeProperty("transition-duration");
      if (open) void surface.offsetWidth;
    } else {
      surface.style.transitionDuration = "0ms";
    }

    surface.toggleAttribute("data-menu-visible", open);

    if (!animate) {
      panel.hidden = !open;
      if (!open) unpin(panel);
      requestAnimationFrame(() => surface.style.removeProperty("transition-duration"));
    } else if (!open) {
      surface.addEventListener(
        "transitionend",
        () => {
          if (!isOpen()) {
            panel.hidden = true;
            unpin(panel);
            if (panel.contains(document.activeElement)) button.focus();
          }
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
      // NOTE: a pinned panel no longer moves with the page, so scrolling to the
      // focused item would leave it hanging away from its trigger.
      panel.querySelector<HTMLElement>(FOCUSABLE)?.focus({ preventScroll: isPinned(panel) });
    }
  });

  const closeIfPinned = (): void => {
    if (isOpen() && isPinned(panel)) close();
  };
  document.addEventListener("scroll", closeIfPinned, { capture: true, passive: true });
  window.addEventListener("resize", closeIfPinned, { passive: true });

  if (Object.hasOwn(root.dataset, "menuHover")) {
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

  document.addEventListener("keydown", (event: KeyboardEvent) => {
    if (event.key !== "Escape" || !isOpen()) return;
    const hadFocus = root.contains(document.activeElement);
    close(true);
    if (hadFocus) button.focus();
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

const wire = (scope: ParentNode = document): void => {
  if (scope instanceof HTMLElement && scope.matches("[data-menu]")) init(scope);
  for (const root of scope.querySelectorAll<HTMLElement>("[data-menu]")) {
    init(root);
  }
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => wire());
} else {
  wire();
}

document.addEventListener("htmx:load", (evt) => {
  const el = (evt as CustomEvent).detail?.elt;
  if (el instanceof Element) wire(el);
});
