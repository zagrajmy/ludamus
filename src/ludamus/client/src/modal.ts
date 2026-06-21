import {
  disablePageScroll,
  enablePageScroll,
  markScrollable,
  unmarkScrollable,
} from "@fluejs/noscroll";
import { initTouchHandler, resetTouchHandler } from "@fluejs/noscroll/touch";

interface NavigateEvent {
  canIntercept: boolean;
  hashChange: boolean;
  navigationType: "push" | "replace" | "reload" | "traverse";
  destination: { url: string };
  intercept: () => void;
}

interface Navigation {
  addEventListener(type: "navigate", handler: (e: NavigateEvent) => void): void;
}

/** ~16% lack Navigation API (Firefox on Android, IE11, older Safari). Click interception only in old browsers. */
const navigation = (globalThis as { navigation?: Navigation }).navigation;

const scrollLockTargets = new Set<HTMLDialogElement>();
const markedScrollables = new Map<HTMLDialogElement, HTMLElement[]>();
let touchHandlerInitialized = false;

// Page scroll lock for open modals. Two cooperating pieces, owned together so
// they can never desync:
//   1. `@fluejs/noscroll` disables page scroll and compensates for the
//      scrollbar width (avoids a desktop layout shift when it disappears).
//   2. A `position: fixed` body pin. iOS Safari ignores `overflow: hidden` on
//      <body>, so the document keeps its scroll offset while a modal is open. A
//      top-layer dialog opened over a scrolled document then hit-tests as if
//      the page were at the top: taps on the visually-centred Close button land
//      on the content behind the modal, so the X feels dead. Pinning the body
//      and offsetting it by the prior scroll forces the document offset to 0,
//      which truly locks iOS and realigns the modal's hit region. The scroll
//      position is restored on unlock.
let pageLocked = false;
let pinnedScrollY = 0;

const lockPage = (): void => {
  if (pageLocked) return;
  pinnedScrollY = window.scrollY;
  const { style } = document.body;
  style.position = "fixed";
  style.top = `-${pinnedScrollY}px`;
  style.left = "0";
  style.right = "0";
  style.width = "100%";
  disablePageScroll();
  pageLocked = true;
};

const unlockPage = (): void => {
  if (!pageLocked) return;
  enablePageScroll();
  const { style } = document.body;
  style.position = "";
  style.top = "";
  style.left = "";
  style.right = "";
  style.width = "";
  pageLocked = false;
  window.scrollTo(0, pinnedScrollY);
};

const getScrollableElements = (dialog: HTMLDialogElement): HTMLElement[] => {
  const candidates = [dialog, ...dialog.querySelectorAll<HTMLElement>("*")];
  return candidates.filter((element) => {
    const overflowY = window.getComputedStyle(element).overflowY;
    return (
      (overflowY === "auto" || overflowY === "scroll") &&
      element.scrollHeight > element.clientHeight
    );
  });
};

const syncPageScrollLock = (): void => {
  const openDialogs = [
    ...document.querySelectorAll<HTMLDialogElement>("dialog.modal[open]"),
  ];
  const openDialogSet = new Set(openDialogs);

  if (openDialogs.length > 0) {
    lockPage();
  }
  if (openDialogs.length > 0 && !touchHandlerInitialized) {
    initTouchHandler();
    touchHandlerInitialized = true;
  }

  for (const dialog of openDialogs) {
    if (scrollLockTargets.has(dialog)) continue;

    const scrollables = getScrollableElements(dialog);
    if (scrollables.length > 0) {
      markScrollable(scrollables);
      markedScrollables.set(dialog, scrollables);
    }
    scrollLockTargets.add(dialog);
  }

  for (const dialog of scrollLockTargets) {
    if (openDialogSet.has(dialog)) continue;

    const scrollables = markedScrollables.get(dialog);
    if (scrollables && scrollables.length > 0) {
      unmarkScrollable(scrollables);
    }
    markedScrollables.delete(dialog);
    scrollLockTargets.delete(dialog);
  }

  if (openDialogs.length === 0) {
    unlockPage();
    if (touchHandlerInitialized) {
      resetTouchHandler();
      touchHandlerInitialized = false;
    }
  }
};

const getDialog = (id: string): HTMLDialogElement => {
  const element = document.getElementById(id);
  if (!(element instanceof HTMLDialogElement)) {
    throw new Error(`Modal "${id}" is not a <dialog> element`);
  }
  return element;
};

const updateQueryParam = (
  paramName: string,
  value: string | null,
  { replaceHistory = false } = {},
): void => {
  const url = new URL(window.location.href);
  const current = url.searchParams.get(paramName);

  if (value === null) {
    if (!current) return;
    url.searchParams.delete(paramName);
  } else {
    const next = String(value);
    if (current === next) return;
    url.searchParams.set(paramName, next);
  }

  if (replaceHistory) {
    window.history.replaceState({}, "", url);
    return;
  }
  window.history.pushState({}, "", url);
};

const getLinkableByModalId = (
  id: string,
): { paramName: string; paramValue: string } | null => {
  const link = document.querySelector(`a[href][aria-controls="${id}"]`);
  if (!link) return null;

  const href = link.getAttribute("href");
  if (!href) return null;

  const hrefUrl = new URL(href, window.location.href);
  const first = hrefUrl.searchParams.entries().next();
  if (first.done) return null;

  const [paramName, paramValue] = first.value;
  return { paramName, paramValue };
};

const prefersReducedMotion = (): boolean =>
  globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

interface ViewTransition {
  finished: Promise<void>;
}

interface ViewTransitionDocument {
  startViewTransition?: (callback: () => void) => ViewTransition;
}

const startViewTransition = (callback: () => void): ViewTransition | null => {
  const doc = document as Document & ViewTransitionDocument;
  if (!doc.startViewTransition) {
    callback();
    return null;
  }
  return doc.startViewTransition(callback);
};

// Shared name that both the session card and its detail modal take on, but only
// for the duration of a transition (assigned here, cleared in `finished`). With
// the same name on the outgoing and incoming element, the browser tweens the
// card's box into the modal's and cross-fades their contents — a layout/
// shared-element transition with no animation library.
const MORPH_NAME = "session-morph";

const sessionCardForModal = (id: string): HTMLElement | null => {
  if (!id.startsWith("session-")) return null;
  const card = document.querySelector(
    `.session-card[data-session-id="${CSS.escape(id.slice("session-".length))}"]`,
  );
  return card instanceof HTMLElement ? card : null;
};

const canMorph = (card: HTMLElement | null): card is HTMLElement =>
  card !== null &&
  !prefersReducedMotion() &&
  typeof (document as Document & ViewTransitionDocument).startViewTransition ===
    "function";

// Assign (or clear) the shared view-transition-names that drive the morph: the
// surface itself (card <-> modal box) plus each `data-morph` element (title,
// author, avatar) so they fly to their counterpart's position instead of
// cross-fading inside the box. Names are constant — only one card/modal pair
// holds them at a time — so modal.css can target the groups for timing.
const setMorph = (root: HTMLElement, active: boolean): void => {
  root.style.viewTransitionName = active ? MORPH_NAME : "";
  root.querySelectorAll<HTMLElement>("[data-morph]").forEach((el) => {
    el.style.viewTransitionName = active ? `morph-${el.dataset.morph}` : "";
  });
};

// Non-session modals (anonymous code, proposals) snapshot themselves and blur
// out via ::view-transition-old(app-modal); instant close where unsupported.
const dismissDialog = (dialog: HTMLDialogElement): void => {
  if (!dialog.open) return;
  if (prefersReducedMotion()) {
    dialog.close();
    return;
  }
  startViewTransition(() => {
    dialog.close();
  });
};

const openModal = (
  id: string,
  { updateUrl = true, replaceHistory = false, animate = true } = {},
): void => {
  const dialog = getDialog(id);
  if (!dialog.open) {
    const card = sessionCardForModal(id);
    if (animate && canMorph(card)) {
      // Old snapshot captures the card's shared elements; the callback hands the
      // names to the now-open modal so the new snapshot morphs card -> modal.
      setMorph(card, true);
      const transition = startViewTransition(() => {
        setMorph(card, false);
        dialog.showModal();
        setMorph(dialog, true);
        syncPageScrollLock();
      });
      void transition?.finished.finally(() => {
        setMorph(dialog, false);
      });
    } else {
      dialog.showModal();
      syncPageScrollLock();
    }
  } else {
    syncPageScrollLock();
  }

  if (updateUrl) {
    const linkable = getLinkableByModalId(id);
    if (linkable) {
      updateQueryParam(linkable.paramName, linkable.paramValue, {
        replaceHistory,
      });
    }
  }
};

const closeModal = (
  id: string,
  { updateUrl = true, replaceHistory = true, animate = true } = {},
): void => {
  const dialog = getDialog(id);
  if (dialog.open) {
    const card = sessionCardForModal(id);
    if (animate && canMorph(card)) {
      // Mirror of open: old snapshot holds the modal, the callback hands the
      // names back to the card so the modal collapses into it.
      setMorph(dialog, true);
      const transition = startViewTransition(() => {
        dialog.close();
        setMorph(dialog, false);
        setMorph(card, true);
        syncPageScrollLock();
      });
      void transition?.finished.finally(() => {
        setMorph(card, false);
      });
    } else {
      dismissDialog(dialog);
      syncPageScrollLock();
    }
  }

  if (updateUrl) {
    const linkable = getLinkableByModalId(id);
    if (!linkable) return;

    const current = new URLSearchParams(window.location.search).get(
      linkable.paramName,
    );
    if (current === linkable.paramValue) {
      updateQueryParam(linkable.paramName, null, { replaceHistory });
    }
  }
};

const syncModalsFromUrl = (): void => {
  const searchParams = new URLSearchParams(window.location.search);

  document.querySelectorAll("dialog.modal[open]").forEach((dialog) => {
    closeModal(dialog.id, { updateUrl: false, animate: false });
  });

  document.querySelectorAll("a[href][aria-controls]").forEach((link) => {
    const href = link.getAttribute("href");
    const modalId = link.getAttribute("aria-controls");
    if (!href || !modalId) return;

    const target = document.getElementById(modalId);
    if (
      !(target instanceof HTMLDialogElement) ||
      !target.classList.contains("modal")
    )
      return;

    const hrefUrl = new URL(href, window.location.href);
    for (const [paramName, paramValue] of hrefUrl.searchParams) {
      if (searchParams.get(paramName) === paramValue) {
        openModal(modalId, { updateUrl: false, animate: false });
        return;
      }
    }
  });
};

document.addEventListener(
  "cancel",
  (event) => {
    const target = event.target;
    if (
      !(target instanceof HTMLDialogElement) ||
      !target.classList.contains("modal")
    )
      return;

    event.preventDefault();
    closeModal(target.id);
  },
  true,
);

document.addEventListener("close", syncPageScrollLock, true);

window.addEventListener("pagehide", () => {
  for (const scrollables of markedScrollables.values()) {
    if (scrollables.length > 0) {
      unmarkScrollable(scrollables);
    }
  }
  markedScrollables.clear();
  scrollLockTargets.clear();
  unlockPage();
  if (touchHandlerInitialized) {
    resetTouchHandler();
    touchHandlerInitialized = false;
  }
});

if (navigation) {
  navigation.addEventListener("navigate", (e) => {
    if (e.navigationType !== "push") return;
    if (!e.canIntercept || e.hashChange) return;

    const url = new URL(e.destination.url);
    if (url.origin !== location.origin || url.pathname !== location.pathname)
      return;

    for (const link of document.querySelectorAll("a[href][aria-controls]")) {
      const href = link.getAttribute("href");
      const modalId = link.getAttribute("aria-controls");
      if (!href || !modalId) continue;

      const hrefUrl = new URL(href, location.href);
      if (hrefUrl.pathname !== url.pathname) continue;

      const matches =
        hrefUrl.searchParams.size > 0 &&
        [...hrefUrl.searchParams].every(
          ([k, v]) => url.searchParams.get(k) === v,
        );
      if (!matches) continue;

      const target = document.getElementById(modalId);
      if (
        !(target instanceof HTMLDialogElement) ||
        !target.classList.contains("modal")
      )
        continue;

      e.intercept();
      openModal(modalId, { updateUrl: false });
      return;
    }
  });
}

const stopModalCloseEvent = (event: Event): void => {
  event.preventDefault();
  event.stopPropagation();
  if ("stopImmediatePropagation" in event) {
    event.stopImmediatePropagation();
  }
};

const closeFromTrigger = (event: Event): void => {
  const eventTarget = event.target;
  if (!(eventTarget instanceof Element)) return;

  const closeTrigger = eventTarget.closest("[data-modal-close]");
  if (!closeTrigger) return;

  const id = closeTrigger.getAttribute("data-modal-close");
  if (!id) return;

  stopModalCloseEvent(event);
  closeModal(id);
};

const setupModalCloseTriggers = (): void => {
  document.querySelectorAll("[data-modal-close]").forEach((trigger) => {
    trigger.addEventListener("touchend", closeFromTrigger, { capture: true });
    trigger.addEventListener("click", closeFromTrigger, { capture: true });
  });
};

document.addEventListener("click", (event) => {
  const eventTarget = event.target;
  if (!(eventTarget instanceof Element)) return;

  // Fallback link interception handled by setupFallbackLinkHandlers below.

  if (
    !(eventTarget instanceof HTMLDialogElement) ||
    !eventTarget.classList.contains("modal")
  )
    return;

  const rect = eventTarget.getBoundingClientRect();
  const isInside =
    event.clientX >= rect.left &&
    event.clientX <= rect.right &&
    event.clientY >= rect.top &&
    event.clientY <= rect.bottom;

  if (!isInside) closeModal(eventTarget.id);
});

window.addEventListener("popstate", syncModalsFromUrl);

syncModalsFromUrl();
setupModalCloseTriggers();

// In browsers without Navigation API (WebKit, older Firefox), attach click
// handlers directly to modal-trigger links so preventDefault fires before
// the browser starts navigation.
const setupFallbackLinkHandlers = (): void => {
  document.querySelectorAll("a[href][aria-controls]").forEach((link) => {
    const modalId = link.getAttribute("aria-controls");
    if (!modalId) return;

    const target = document.getElementById(modalId);
    if (
      !(target instanceof HTMLDialogElement) ||
      !target.classList.contains("modal")
    )
      return;

    link.addEventListener("click", (e) => {
      e.preventDefault();
      openModal(modalId);
    });
  });
};

setupFallbackLinkHandlers();

export { closeModal, openModal };
