// A panel that is a modal dialog only on a phone: the bottom sheet and the
// session filter sheet. No media query reaches ARIA, so the dialog role goes
// on and comes off with the breakpoint, and Tab is kept inside by hand. The
// scroll lock behind it is keyed on aria-modal in index.css.

export const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled], [type="hidden"]),' +
  ' select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

// offsetParent is null in a display:none subtree, which drops hidden parts.
export const focusableIn = (panel: HTMLElement): HTMLElement[] =>
  [...panel.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((item) => item.offsetParent !== null);

export const setModal = (panel: HTMLElement, modal: boolean): void => {
  if (modal) {
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-modal", "true");
  } else {
    panel.removeAttribute("role");
    panel.removeAttribute("aria-modal");
  }
};

// defaultPrevented means a control inside already claimed the key, and a
// dialog nested in the panel owns its own keys.
const ownsKey = (panel: HTMLElement, event: KeyboardEvent): boolean =>
  panel.getAttribute("aria-modal") === "true" &&
  !event.defaultPrevented &&
  event.target instanceof Element &&
  event.target.closest('dialog, [aria-modal="true"]') === panel;

const wrapTab = (panel: HTMLElement, event: KeyboardEvent): void => {
  const items = focusableIn(panel);
  const [edge, wrapTo] = event.shiftKey ? [items.at(0), items.at(-1)] : [items.at(-1), items.at(0)];
  if (!wrapTo || document.activeElement !== edge) return;
  event.preventDefault();
  wrapTo.focus();
};

// A dialog that leaves focus behind it is a dialog only to the eye, so Tab
// wraps at the ends rather than walking out into the page underneath.
export const holdFocus = (panel: HTMLElement, onEscape?: () => void): void => {
  const keys: Partial<Record<string, (event: KeyboardEvent) => void>> = {
    Escape: onEscape,
    Tab: (event) => wrapTab(panel, event),
  };
  panel.addEventListener("keydown", (event) => {
    if (ownsKey(panel, event)) keys[event.key]?.(event);
  });
};
