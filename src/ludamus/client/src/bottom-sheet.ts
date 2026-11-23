// [data-bottom-sheet]: drag, dismiss and dialog semantics for the sheet the
// {% bottom_sheet %} tag renders. Below `lg` the element is a modal sheet;
// from `lg` up it is a card and all of this stays idle.
//
// NOTE: no `inert` on the page behind the sheet. #confirm-dialog and the flash
// region live there, and a modal inside an inert subtree stays inert.

import { requestConfirm } from "./confirm";
import { holdFocus, setModal } from "./sheet-dialog";

const SHEET_WIDTH = globalThis.matchMedia("(width < 64rem)");
const TYPING_FIELD = 'input:not([type="radio"], [type="checkbox"], [type="hidden"]), textarea';
const DRAG_THRESHOLD_PX = 60;
const DRAG_TO_HALF_LIMIT_PX = 360;
const TAP_SLOP_PX = 4;
const CLOSE_MS = 280;

type Snap = "full" | "half";

interface Sheet {
  backdrop: HTMLElement;
  closeLink: HTMLAnchorElement;
  dirty: boolean;
  el: HTMLElement;
  handle: HTMLElement;
  openedInThisDocument: boolean;
  title: HTMLElement;
  wasModal: boolean;
}

const root = document.documentElement;
// Set by components/bottom-sheet-head.html, which reads the same key before
// first paint.
const snapKey = root.dataset.bottomSheetSnapKey;

// The still flag from bottom-sheet-head.html only has to outlast the first
// paint, which the inner frame comes after; from then on the sheet animates.
globalThis.requestAnimationFrame(() =>
  globalThis.requestAnimationFrame(() => delete root.dataset.bottomSheetStill),
);

const rememberSnap = (snap: Snap): void => {
  root.dataset.bottomSheetSnap = snap;
  if (!snapKey) return;
  try {
    globalThis.sessionStorage.setItem(snapKey, snap);
  } catch {
    // Blocked storage only costs the height surviving a reload.
  }
};

const part = <T extends HTMLElement>(scope: ParentNode | null, selector: string): T => {
  const found = scope?.querySelector<T>(selector);
  if (!found) throw new Error(`bottom sheet is missing ${selector}`);
  return found;
};

const isModal = (sheet: Sheet): boolean =>
  SHEET_WIDTH.matches && (sheet.el.dataset.open !== undefined || sheet.el.matches(":target"));

const currentSnap = (sheet: Sheet): Snap =>
  (root.dataset.bottomSheetSnap ?? sheet.el.dataset.height) === "full" ? "full" : "half";

const syncHandleLabel = (sheet: Sheet): void => {
  const { labelGrow, labelShrink } = sheet.handle.dataset;
  const label = currentSnap(sheet) === "full" ? labelShrink : labelGrow;
  if (label) sheet.handle.setAttribute("aria-label", label);
};

const setSnap = (sheet: Sheet, snap: Snap): void => {
  rememberSnap(snap);
  syncHandleLabel(sheet);
};

const syncModal = (sheet: Sheet): void => {
  const modal = isModal(sheet);
  sheet.el.toggleAttribute("data-closing", false);
  sheet.backdrop.hidden = !modal;
  setModal(sheet.el, modal);
  if (modal && !sheet.wasModal) sheet.title.focus({ preventScroll: true });
  sheet.wasModal = modal;
};

const cameFrom = (target: URL): boolean =>
  document.referrer === target.href && target.pathname !== globalThis.location.pathname;

const leave = (sheet: Sheet): void => {
  const target = new URL(sheet.closeLink.href);
  const back = sheet.openedInThisDocument || cameFrom(target);
  sheet.openedInThisDocument = false;
  if (back) globalThis.history.back();
  else globalThis.location.replace(target);
};

const close = (sheet: Sheet): void => {
  sheet.el.toggleAttribute("data-closing", true);
  globalThis.setTimeout(() => leave(sheet), CLOSE_MS);
};

const dismiss = (sheet: Sheet): void => {
  sheet.el.style.removeProperty("height");
  if (!sheet.dirty) {
    close(sheet);
    return;
  }
  const { discardLabel, discardMessage } = sheet.el.dataset;
  requestConfirm(discardMessage ?? "", discardLabel ?? null, () => {
    sheet.dirty = false;
    close(sheet);
  });
};

const wireDismiss = (sheet: Sheet): void => {
  sheet.closeLink.addEventListener("click", (event) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey) return;
    event.preventDefault();
    dismiss(sheet);
  });
  sheet.backdrop.addEventListener("click", () => dismiss(sheet));
  holdFocus(sheet.el, () => dismiss(sheet));
};

const wireForm = (sheet: Sheet): void => {
  // Half a screen minus the keyboard leaves no room to see what is being typed.
  sheet.el.addEventListener("focusin", ({ target }) => {
    if (isModal(sheet) && target instanceof Element && target.matches(TYPING_FIELD)) {
      setSnap(sheet, "full");
    }
  });
  sheet.el.addEventListener("input", () => {
    sheet.dirty = true;
  });
  sheet.el.addEventListener(
    "submit",
    () => {
      sheet.dirty = false;
    },
    true,
  );
  globalThis.addEventListener("beforeunload", (event) => {
    if (sheet.dirty) event.preventDefault();
  });
};

const shrinkOrDismiss = (sheet: Sheet, delta: number): void => {
  if (currentSnap(sheet) === "full" && delta < DRAG_TO_HALF_LIMIT_PX) setSnap(sheet, "half");
  else dismiss(sheet);
};

const snapAfterDrag = (sheet: Sheet, delta: number): void => {
  if (delta < -DRAG_THRESHOLD_PX) setSnap(sheet, "full");
  else if (delta > DRAG_THRESHOLD_PX) shrinkOrDismiss(sheet, delta);
};

const wireDrag = (sheet: Sheet): void => {
  const { el, handle } = sheet;
  let startY: number | null = null;
  let startHeight = 0;
  let dragged = false;

  handle.addEventListener("pointerdown", (event) => {
    startY = event.clientY;
    startHeight = el.getBoundingClientRect().height;
    dragged = false;
    handle.setPointerCapture(event.pointerId);
    el.toggleAttribute("data-dragging", true);
  });

  handle.addEventListener("pointermove", (event) => {
    if (startY === null) return;
    const delta = event.clientY - startY;
    dragged ||= Math.abs(delta) > TAP_SLOP_PX;
    if (dragged) el.style.height = `${startHeight - delta}px`;
  });

  const endDrag = (event: PointerEvent): void => {
    if (startY === null) return;
    const delta = event.clientY - startY;
    startY = null;
    el.toggleAttribute("data-dragging", false);
    if (!dragged) return;
    el.style.removeProperty("height");
    snapAfterDrag(sheet, delta);
  };
  handle.addEventListener("pointerup", endDrag);
  handle.addEventListener("pointercancel", endDrag);

  // A drag ends in a click too; only a tap or Enter toggles.
  handle.addEventListener("click", () => {
    if (!dragged) setSnap(sheet, currentSnap(sheet) === "full" ? "half" : "full");
    dragged = false;
  });
};

const wireViewport = (sheet: Sheet): void => {
  const fitKeyboard = (): void => {
    const viewport = globalThis.visualViewport;
    if (!viewport) return;
    const keyboard = Math.max(0, globalThis.innerHeight - viewport.height - viewport.offsetTop);
    sheet.el.style.setProperty("--bottom-sheet-keyboard", `${keyboard}px`);
  };
  globalThis.visualViewport?.addEventListener("resize", fitKeyboard);
  globalThis.visualViewport?.addEventListener("scroll", fitKeyboard);

  globalThis.addEventListener("hashchange", () => {
    if (sheet.el.matches(":target")) sheet.openedInThisDocument = true;
    syncModal(sheet);
  });
  // Back-forward cache restores a sheet that left mid-close.
  globalThis.addEventListener("pageshow", () => syncModal(sheet));
  SHEET_WIDTH.addEventListener("change", () => syncModal(sheet));
};

const init = (el: HTMLElement): void => {
  const sheet: Sheet = {
    backdrop: part(el.parentElement, "[data-bottom-sheet-backdrop]"),
    closeLink: part<HTMLAnchorElement>(el, "[data-bottom-sheet-close]"),
    dirty: false,
    el,
    handle: part(el, "[data-bottom-sheet-handle]"),
    openedInThisDocument: false,
    title: part(el, "[data-bottom-sheet-title]"),
    wasModal: false,
  };
  wireDismiss(sheet);
  wireForm(sheet);
  wireDrag(sheet);
  wireViewport(sheet);

  // A form sent back with errors opens at full height, whatever height the
  // user left the sheet at before posting it.
  const invalid = el.querySelector('[aria-invalid="true"]');
  if (invalid) rememberSnap("full");
  syncHandleLabel(sheet);
  syncModal(sheet);
  if (isModal(sheet)) invalid?.scrollIntoView({ block: "center" });
};

for (const sheet of document.querySelectorAll<HTMLElement>("[data-bottom-sheet]")) init(sheet);
