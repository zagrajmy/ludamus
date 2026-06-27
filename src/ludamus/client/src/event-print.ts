/**
 * Ctrl/Cmd+P hijack on the public event page.
 *
 * `Ctrl/Cmd+P` on the event page would otherwise print the interactive chrome
 * (nav, filters) — garbage on paper. We honor the intent behind the gesture
 * ("give me paper now") by routing it to the print-ready `/print` page instead.
 *
 * `preventDefault()` on the `keydown` suppresses the native print dialog in
 * current Chrome/Firefox/Edge/Safari. File->Print and the toolbar cannot be
 * intercepted from JS; the event page's `@media print` fallback covers those.
 */

function getPrintUrl(): string | null {
  const link = document.querySelector<HTMLAnchorElement>("[data-event-print]");
  return link?.getAttribute("href") ?? null;
}

function isEditing(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  if (el.isContentEditable) return true;
  return ["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName);
}

function onKeydown(event: KeyboardEvent): void {
  const isPrintCombo = (event.metaKey || event.ctrlKey) && (event.key === "p" || event.key === "P");
  if (!isPrintCombo || event.altKey || event.shiftKey) return;
  // Don't steal the gesture mid-edit — navigating away would discard input.
  if (isEditing(event.target)) return;

  const url = getPrintUrl();
  if (!url) return;

  event.preventDefault();
  globalThis.location.assign(url);
}

document.addEventListener("keydown", onKeydown);
