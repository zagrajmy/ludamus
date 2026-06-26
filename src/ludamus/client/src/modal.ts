import {
  disablePageScroll,
  enablePageScroll,
  markScrollable,
  unmarkScrollable,
} from "@fluejs/noscroll";
import { initTouchHandler, resetTouchHandler } from "@fluejs/noscroll/touch";

interface NavigateEvent {
  canIntercept: boolean;
  destination: { url: string };
  hashChange: boolean;
  intercept: () => void;
  navigationType: "push" | "reload" | "replace" | "traverse";
}

interface Navigation {
  addEventListener(type: "navigate", handler: (e: NavigateEvent) => void): void;
}

/** ~16% lack Navigation API (Firefox on Android, IE11, older Safari). Click interception only in old browsers. */
const { navigation } = globalThis as { navigation?: Navigation };

const scrollLockTargets = new Set<HTMLDialogElement>();
const markedScrollables = new Map<HTMLDialogElement, HTMLElement[]>();
let touchHandlerInitialized = false;

// Page scroll lock for open modals. Two strategies; the first that applies wins:
//
//   A. App-shell (preferred). When the page uses the `#app-scroll` container
//      (the default web layout), the document itself never scrolls — that inner
//      element does. A top-layer dialog therefore always hit-tests over an
//      unscrolled document, and the background is locked by simply freezing the
//      container's overflow. Freezing a non-document scroller keeps its offset
//      and moves nothing: no body pin, no scroll save/restore, so the page can't
//      jump or flash the top on open/close.
//
//   B. Body-pin fallback. Layouts that still scroll the document (panel, print)
//      have no `#app-scroll`. There `@fluejs/noscroll` disables page scroll and
//      compensates the scrollbar width, and on iOS/Safari a `position: fixed`
//      body pin forces the document offset to 0 so the top-layer Close button
//      stays tappable over a scrolled page; the offset is restored on unlock.
let pageLocked = false;
let pinnedScrollY = 0;
let bodyPinned = false;
let lockedScrollRoot: HTMLElement | null = null;

const getScrollRoot = (): HTMLElement | null =>
  document.getElementById("app-scroll");

// The `position: fixed` body pin (above) is only needed where `overflow: hidden`
// on a scrolled <body> fails to lock the page and misaligns a top-layer dialog's
// hit region — i.e. iOS / Safari. Everywhere else `disablePageScroll` alone
// locks cleanly, and pinning the body would only shift layout (and, during a
// View Transition, jitter). Restrict the pin like Vaul does.
const needsBodyPin = (): boolean => {
  const ua = navigator.userAgent;
  const iOS =
    /iP(hone|ad|od)/.test(ua) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const safari = /^((?!chrome|android|crios|fxios).)*safari/i.test(ua);
  return iOS || safari;
};

// While a morph View Transition is in flight, lock/unlock must not run between
// the two snapshots (it would animate the scroll-offset change). The morph paths
// lock before / unlock after the transition and suspend this helper in between.
let scrollLockSuspended = false;

const lockPage = (): void => {
  if (pageLocked) return;
  // Strategy A: freeze the app-shell scroll container. Nothing moves, so there
  // is nothing to restore on unlock.
  const root = getScrollRoot();
  if (root) {
    root.style.overflow = "hidden";
    lockedScrollRoot = root;
    pageLocked = true;
    return;
  }
  // Strategy B: document-scrolling layout — pin the body on iOS/Safari and lock
  // with noscroll.
  pinnedScrollY = window.scrollY;
  if (needsBodyPin()) {
    const { style } = document.body;
    style.position = "fixed";
    style.top = `-${pinnedScrollY}px`;
    style.left = "0";
    style.right = "0";
    style.width = "100%";
    bodyPinned = true;
  }
  disablePageScroll();
  pageLocked = true;
};

const unlockPage = (): void => {
  if (!pageLocked) return;
  pageLocked = false;
  if (lockedScrollRoot) {
    lockedScrollRoot.style.overflow = "";
    lockedScrollRoot = null;
    return;
  }
  enablePageScroll();
  if (!bodyPinned) return;
  const { style } = document.body;
  style.position = "";
  style.top = "";
  style.left = "";
  style.right = "";
  style.width = "";
  bodyPinned = false;
  // Removing the fixed pin drops the document back to scroll offset 0; restore
  // the prior offset synchronously, in the same task, so the page paints once at
  // the right place. Deferring this to rAF lets Safari paint a frame (or several,
  // when the unlock trails a closing View Transition) at the top first — the
  // visible "jump to the top and back" on modal close.
  window.scrollTo(0, pinnedScrollY);
};

const getScrollableElements = (dialog: HTMLDialogElement): HTMLElement[] => {
  const candidates = [dialog, ...dialog.querySelectorAll<HTMLElement>("*")];
  return candidates.filter((element) => {
    const { overflowY } = globalThis.getComputedStyle(element);
    return (
      (overflowY === "auto" || overflowY === "scroll") &&
      element.scrollHeight > element.clientHeight
    );
  });
};

const syncPageScrollLock = (): void => {
  if (scrollLockSuspended) return;
  const openDialogs = [
    ...document.querySelectorAll<HTMLDialogElement>("dialog.modal[open]"),
  ];
  const openDialogSet = new Set(openDialogs);

  if (openDialogs.length > 0) {
    lockPage();
  }

  // The noscroll touch handler and per-dialog scrollable marking only matter for
  // the body-pin fallback (strategy B). The app-shell path freezes the container
  // and leaves the dialog's own scroll areas alone, so skip all of it there.
  if (!lockedScrollRoot) {
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
    throw new TypeError(`Modal "${id}" is not a <dialog> element`);
  }
  return element;
};

const updateQueryParam = (
  paramName: string,
  value: string | null,
  { replaceHistory = false } = {},
): void => {
  const url = new URL(globalThis.location.href);
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
    globalThis.history.replaceState({}, "", url);
    return;
  }
  globalThis.history.pushState({}, "", url);
};

const getLinkableByModalId = (
  id: string,
): { paramName: string; paramValue: string } | null => {
  const link = document.querySelector(`a[href][aria-controls="${id}"]`);
  if (!link) return null;

  const href = link.getAttribute("href");
  if (!href) return null;

  const hrefUrl = new URL(href, globalThis.location.href);
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
  for (const el of root.querySelectorAll<HTMLElement>("[data-morph]")) {
    el.style.viewTransitionName = active ? `morph-${el.dataset.morph}` : "";
  }
};

// One owner for the morph protocol so open and close can't drift and the
// scroll-lock ordering is enforced once: run `before` (pre-capture — lock the
// page / name the outgoing side), suspend the scroll-lock sync so the
// synchronous `close` event and the body mutation can't land between the two
// snapshots, swap the DOM inside the View Transition, then on `finished` run
// `settle` and resume the lock. `before`/`swap`/`settle` carry the only parts
// that differ between the two directions.
const morphTransition = (steps: {
  before: () => void;
  settle: () => void;
  swap: () => void;
}): void => {
  steps.before();
  scrollLockSuspended = true;
  const transition = startViewTransition(steps.swap);
  const finish = (): void => {
    steps.settle();
    scrollLockSuspended = false;
    syncPageScrollLock();
  };
  if (transition) void transition.finished.finally(finish);
  else finish();
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
  { animate = true, replaceHistory = false, updateUrl = true } = {},
): void => {
  const dialog = getDialog(id);
  if (dialog.open) {
    syncPageScrollLock();
  } else {
    const card = sessionCardForModal(id);
    if (animate && canMorph(card)) {
      morphTransition({
        // Lock scroll before the capture so the body mutation lands in the old
        // snapshot, not the animated delta; name the card's shared elements so
        // the new snapshot morphs card -> modal.
        before: () => {
          lockPage();
          setMorph(card, true);
        },
        settle: () => {
          setMorph(dialog, false);
          card.style.visibility = "";
          card.style.transition = "";
        },
        swap: () => {
          setMorph(card, false);
          // Hide the source card once its snapshot is captured, so it doesn't
          // show through the cross-fading modal from behind and read as a
          // duplicate. `transition: none` defeats the card's `duration-100`
          // transition, which would otherwise swallow the change before the new
          // snapshot is taken.
          card.style.transition = "none";
          card.style.visibility = "hidden";
          dialog.showModal();
          setMorph(dialog, true);
        },
      });
    } else {
      dialog.showModal();
      syncPageScrollLock();
    }
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
  { animate = true, replaceHistory = true, updateUrl = true } = {},
): void => {
  const dialog = getDialog(id);
  if (dialog.open) {
    const card = sessionCardForModal(id);
    if (animate && canMorph(card)) {
      morphTransition({
        // Old snapshot holds the modal; the swap hands the names back to the
        // card so it collapses into the card.
        before: () => setMorph(dialog, true),
        settle: () => setMorph(card, false),
        swap: () => {
          dialog.close();
          setMorph(dialog, false);
          setMorph(card, true);
        },
      });
    } else {
      dismissDialog(dialog);
      syncPageScrollLock();
    }
  }

  if (updateUrl) {
    const linkable = getLinkableByModalId(id);
    if (!linkable) return;

    const current = new URLSearchParams(globalThis.location.search).get(
      linkable.paramName,
    );
    if (current === linkable.paramValue) {
      updateQueryParam(linkable.paramName, null, { replaceHistory });
    }
  }
};

const syncModalsFromUrl = (): void => {
  const searchParams = new URLSearchParams(globalThis.location.search);

  for (const dialog of document.querySelectorAll("dialog.modal[open]")) {
    closeModal(dialog.id, { animate: false, updateUrl: false });
  }

  for (const link of document.querySelectorAll("a[href][aria-controls]")) {
    const href = link.getAttribute("href");
    const modalId = link.getAttribute("aria-controls");
    if (!href || !modalId) continue;

    const target = document.getElementById(modalId);
    if (
      !(target instanceof HTMLDialogElement) ||
      !target.classList.contains("modal")
    )
      continue;

    const hrefUrl = new URL(href, globalThis.location.href);
    for (const [paramName, paramValue] of hrefUrl.searchParams) {
      if (searchParams.get(paramName) === paramValue) {
        openModal(modalId, { animate: false, updateUrl: false });
        return;
      }
    }
  }
};

document.addEventListener(
  "cancel",
  (event) => {
    const { target } = event;
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

  const closeTrigger = eventTarget.closest<HTMLElement>("[data-modal-close]");
  if (!closeTrigger) return;

  const id = closeTrigger.dataset.modalClose;
  if (!id) return;

  stopModalCloseEvent(event);
  closeModal(id);
};

const setupModalCloseTriggers = (): void => {
  for (const trigger of document.querySelectorAll("[data-modal-close]")) {
    trigger.addEventListener("touchend", closeFromTrigger, { capture: true });
    trigger.addEventListener("click", closeFromTrigger, { capture: true });
  }
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

globalThis.addEventListener("popstate", syncModalsFromUrl);

syncModalsFromUrl();
setupModalCloseTriggers();

// In browsers without Navigation API (WebKit, older Firefox), attach click
// handlers directly to modal-trigger links so preventDefault fires before
// the browser starts navigation.
const setupFallbackLinkHandlers = (): void => {
  for (const link of document.querySelectorAll("a[href][aria-controls]")) {
    const modalId = link.getAttribute("aria-controls");
    if (!modalId) continue;

    const target = document.getElementById(modalId);
    if (
      !(target instanceof HTMLDialogElement) ||
      !target.classList.contains("modal")
    )
      continue;

    link.addEventListener("click", (e) => {
      e.preventDefault();
      openModal(modalId);
    });
  }
};

setupFallbackLinkHandlers();

export { closeModal, openModal };
