// [data-bottom-sheet]: drag, dismiss and dialog semantics for
// components/bottom-sheet-*.html. Below `lg` the element is a modal sheet;
// from `lg` up it is a card and all of this stays idle.
//
// NOTE: no `inert` on the page behind the sheet. #confirm-dialog and the flash
// region live there, and a modal inside an inert subtree stays inert.

import { requestConfirm } from "./confirm";

const SHEET_WIDTH = globalThis.matchMedia("(width < 64rem)");
const SNAP_KEY = `bottom-sheet-snap:${globalThis.location.pathname}`;
const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([type="hidden"]), select, textarea, [tabindex]:not([tabindex="-1"])';
const TYPING_FIELD = 'input:not([type="radio"], [type="checkbox"], [type="hidden"]), textarea';
const DRAG_THRESHOLD_PX = 60;
const DRAG_TO_HALF_LIMIT_PX = 360;
const TAP_SLOP_PX = 4;
const CLOSE_MS = 280;

type Snap = "full" | "half";

const root = document.documentElement;

const rememberSnap = (snap: Snap): void => {
  root.dataset.bottomSheetSnap = snap;
  try {
    globalThis.sessionStorage.setItem(SNAP_KEY, snap);
  } catch {
    // Blocked storage only costs the height surviving a reload.
  }
};

const init = (sheet: HTMLElement): void => {
  const handle = sheet.querySelector<HTMLElement>("[data-bottom-sheet-handle]");
  const closeLink = sheet.querySelector<HTMLAnchorElement>("[data-bottom-sheet-close]");
  const title = sheet.querySelector<HTMLElement>("[data-bottom-sheet-title]");
  const backdrop = sheet.parentElement?.querySelector<HTMLElement>("[data-bottom-sheet-backdrop]");
  if (!handle || !closeLink || !title || !backdrop) return;

  let dirty = false;
  let openedInThisDocument = false;
  let wasModal = false;

  const isModal = (): boolean =>
    SHEET_WIDTH.matches && (sheet.dataset.open !== undefined || sheet.matches(":target"));

  const currentSnap = (): Snap => {
    const snap = root.dataset.bottomSheetSnap ?? sheet.dataset.height;
    return snap === "full" ? "full" : "half";
  };

  const syncHandleLabel = (): void => {
    const label = currentSnap() === "full" ? handle.dataset.labelShrink : handle.dataset.labelGrow;
    if (label) handle.setAttribute("aria-label", label);
  };

  const setSnap = (snap: Snap): void => {
    rememberSnap(snap);
    syncHandleLabel();
  };

  const syncModal = (): void => {
    const modal = isModal();
    sheet.toggleAttribute("data-closing", false);
    backdrop.hidden = !modal;
    if (modal) {
      sheet.setAttribute("role", "dialog");
      sheet.setAttribute("aria-modal", "true");
    } else {
      sheet.removeAttribute("role");
      sheet.removeAttribute("aria-modal");
    }
    if (modal && !wasModal) title.focus({ preventScroll: true });
    wasModal = modal;
  };

  const leave = (): void => {
    const target = new URL(closeLink.href);
    if (openedInThisDocument) {
      openedInThisDocument = false;
      globalThis.history.back();
    } else if (
      document.referrer === target.href &&
      target.pathname !== globalThis.location.pathname
    ) {
      globalThis.history.back();
    } else {
      globalThis.location.replace(target);
    }
  };

  const close = (): void => {
    sheet.toggleAttribute("data-closing", true);
    globalThis.setTimeout(leave, CLOSE_MS);
  };

  const dismiss = (): void => {
    sheet.style.removeProperty("height");
    if (!dirty) {
      close();
      return;
    }
    requestConfirm(sheet.dataset.discardMessage ?? "", sheet.dataset.discardLabel ?? null, () => {
      dirty = false;
      close();
    });
  };

  closeLink.addEventListener("click", (event) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey) return;
    event.preventDefault();
    dismiss();
  });
  backdrop.addEventListener("click", dismiss);

  sheet.addEventListener("keydown", (event) => {
    if (sheet.getAttribute("aria-modal") !== "true" || event.defaultPrevented) return;
    if (event.target instanceof Element && event.target.closest("dialog")) return;
    if (event.key === "Escape") {
      dismiss();
      return;
    }
    if (event.key !== "Tab") return;
    const items = [...sheet.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
      (item) => item.offsetParent !== null,
    );
    const edge = event.shiftKey ? items.at(0) : items.at(-1);
    if (document.activeElement !== edge && document.activeElement !== title) return;
    if (document.activeElement === title && !event.shiftKey) return;
    event.preventDefault();
    (event.shiftKey ? items.at(-1) : items.at(0))?.focus();
  });

  // Half a screen minus the keyboard leaves no room to see what is being typed.
  sheet.addEventListener("focusin", ({ target }) => {
    if (isModal() && target instanceof Element && target.matches(TYPING_FIELD)) setSnap("full");
  });

  sheet.addEventListener("input", () => {
    dirty = true;
  });
  sheet.addEventListener(
    "submit",
    () => {
      dirty = false;
    },
    true,
  );
  globalThis.addEventListener("beforeunload", (event) => {
    if (dirty) event.preventDefault();
  });

  let dragStartY: number | null = null;
  let dragStartHeight = 0;
  let dragged = false;

  handle.addEventListener("pointerdown", (event) => {
    dragStartY = event.clientY;
    dragStartHeight = sheet.getBoundingClientRect().height;
    dragged = false;
    handle.setPointerCapture(event.pointerId);
    sheet.toggleAttribute("data-dragging", true);
  });

  handle.addEventListener("pointermove", (event) => {
    if (dragStartY === null) return;
    const delta = event.clientY - dragStartY;
    dragged ||= Math.abs(delta) > TAP_SLOP_PX;
    if (dragged) sheet.style.height = `${dragStartHeight - delta}px`;
  });

  const endDrag = (event: PointerEvent): void => {
    if (dragStartY === null) return;
    const delta = event.clientY - dragStartY;
    dragStartY = null;
    sheet.toggleAttribute("data-dragging", false);
    if (!dragged) return;
    sheet.style.removeProperty("height");
    if (delta < -DRAG_THRESHOLD_PX) {
      setSnap("full");
    } else if (delta > DRAG_THRESHOLD_PX) {
      if (currentSnap() === "full" && delta < DRAG_TO_HALF_LIMIT_PX) setSnap("half");
      else dismiss();
    }
  };
  handle.addEventListener("pointerup", endDrag);
  handle.addEventListener("pointercancel", endDrag);

  // A drag ends in a click too; only a tap or Enter toggles.
  handle.addEventListener("click", () => {
    if (!dragged) setSnap(currentSnap() === "full" ? "half" : "full");
    dragged = false;
  });

  const fitKeyboard = (): void => {
    const viewport = globalThis.visualViewport;
    if (!viewport) return;
    const keyboard = Math.max(0, globalThis.innerHeight - viewport.height - viewport.offsetTop);
    sheet.style.setProperty("--bottom-sheet-keyboard", `${keyboard}px`);
  };
  globalThis.visualViewport?.addEventListener("resize", fitKeyboard);
  globalThis.visualViewport?.addEventListener("scroll", fitKeyboard);

  globalThis.addEventListener("hashchange", () => {
    if (sheet.matches(":target")) openedInThisDocument = true;
    syncModal();
  });
  // Back-forward cache restores a sheet that left mid-close.
  globalThis.addEventListener("pageshow", syncModal);
  SHEET_WIDTH.addEventListener("change", syncModal);

  syncHandleLabel();
  syncModal();
  if (isModal()) sheet.querySelector('[aria-invalid="true"]')?.scrollIntoView({ block: "center" });
};

for (const sheet of document.querySelectorAll<HTMLElement>("[data-bottom-sheet]")) init(sheet);
