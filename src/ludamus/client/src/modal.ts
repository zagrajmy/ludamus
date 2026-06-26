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

// The page scroll is locked while any modal is open by a pure-CSS rule —
// `body:has(dialog.modal[open]) .app-scroll { overflow: hidden }` (index.css).
// Freezing the app-shell scroll container keeps its offset and moves nothing, so
// there is no body pin, no scroll save/restore, and nothing for this module to
// do: the lock can never desync from whether a modal is open. (The document
// never scrolls under the app-shell, so a top-layer dialog always hit-tests
// correctly — the iOS dead-Close-button case can't arise.)

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

const getLinkableByModalId = (id: string): { paramName: string; paramValue: string } | null => {
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
  typeof (document as Document & ViewTransitionDocument).startViewTransition === "function";

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

// One owner for the morph protocol so open and close can't drift: run `before`
// (pre-capture — name the outgoing side), swap the DOM inside the View
// Transition, then on `finished` run `settle`. `before`/`swap`/`settle` carry
// the only parts that differ between the two directions. The page-scroll lock is
// pure CSS (see top of file), so there is no lock ordering to coordinate here.
const morphTransition = (steps: {
  before: () => void;
  settle: () => void;
  swap: () => void;
}): void => {
  steps.before();
  const transition = startViewTransition(steps.swap);
  if (transition) void transition.finished.finally(steps.settle);
  else steps.settle();
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
  if (!dialog.open) {
    const card = sessionCardForModal(id);
    if (animate && canMorph(card)) {
      morphTransition({
        // Name the card's shared elements so the new snapshot morphs
        // card -> modal. (Scroll locking is pure CSS, keyed off the open dialog.)
        before: () => setMorph(card, true),
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
    }
  }

  if (updateUrl) {
    const linkable = getLinkableByModalId(id);
    if (!linkable) return;

    const current = new URLSearchParams(globalThis.location.search).get(linkable.paramName);
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
    if (!(target instanceof HTMLDialogElement) || !target.classList.contains("modal")) continue;

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
    if (!(target instanceof HTMLDialogElement) || !target.classList.contains("modal")) return;

    event.preventDefault();
    closeModal(target.id);
  },
  true,
);

if (navigation) {
  navigation.addEventListener("navigate", (e) => {
    if (e.navigationType !== "push") return;
    if (!e.canIntercept || e.hashChange) return;

    const url = new URL(e.destination.url);
    if (url.origin !== location.origin || url.pathname !== location.pathname) return;

    for (const link of document.querySelectorAll("a[href][aria-controls]")) {
      const href = link.getAttribute("href");
      const modalId = link.getAttribute("aria-controls");
      if (!href || !modalId) continue;

      const hrefUrl = new URL(href, location.href);
      if (hrefUrl.pathname !== url.pathname) continue;

      const matches =
        hrefUrl.searchParams.size > 0 &&
        [...hrefUrl.searchParams].every(([k, v]) => url.searchParams.get(k) === v);
      if (!matches) continue;

      const target = document.getElementById(modalId);
      if (!(target instanceof HTMLDialogElement) || !target.classList.contains("modal")) continue;

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

  if (!(eventTarget instanceof HTMLDialogElement) || !eventTarget.classList.contains("modal"))
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
    if (!(target instanceof HTMLDialogElement) || !target.classList.contains("modal")) continue;

    link.addEventListener("click", (e) => {
      e.preventDefault();
      openModal(modalId);
    });
  }
};

setupFallbackLinkHandlers();

export { closeModal, openModal };
