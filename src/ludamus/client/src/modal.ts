import {
  disablePageScroll,
  enablePageScroll,
  markScrollable,
  pageScrollIsDisabled,
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
  addEventListener(
    type: "navigate",
    handler: (e: NavigateEvent) => void,
  ): void;
}

/** ~16% lack Navigation API (Firefox on Android, IE11, older Safari). Click interception only in old browsers. */
const navigation = (globalThis as { navigation?: Navigation }).navigation;

const scrollLockTargets = new Set<HTMLDialogElement>();
const markedScrollables = new Map<HTMLDialogElement, HTMLElement[]>();
let touchHandlerInitialized = false;

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

  if (openDialogs.length > 0 && !pageScrollIsDisabled()) {
    disablePageScroll();
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
    if (pageScrollIsDisabled()) {
      enablePageScroll();
    }
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

const openModal = (
  id: string,
  { updateUrl = true, replaceHistory = false } = {},
): void => {
  const dialog = getDialog(id);
  if (!dialog.open) {
    dialog.showModal();
  }
  syncPageScrollLock();

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
  { updateUrl = true, replaceHistory = true } = {},
): void => {
  const dialog = getDialog(id);
  if (dialog.open) {
    dialog.close();
  }
  syncPageScrollLock();

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
    closeModal(dialog.id, { updateUrl: false });
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
        openModal(modalId, { updateUrl: false });
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
  if (pageScrollIsDisabled()) {
    enablePageScroll();
  }
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
