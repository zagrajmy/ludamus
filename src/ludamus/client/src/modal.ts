interface NavigateEvent {
  canIntercept: boolean;
  destination: { url: string };
  hashChange: boolean;
  intercept: (options?: {
    focusReset?: "after-transition" | "manual";
    handler?: () => Promise<void> | void;
    scroll?: "after-transition" | "manual";
  }) => void;
  navigationType: "push" | "reload" | "replace" | "traverse";
}

interface Navigation {
  addEventListener(type: "navigate", handler: (e: NavigateEvent) => void): void;
}

/** ~16% lack Navigation API (Firefox on Android, IE11, older Safari). Click interception only in old browsers. */
const { navigation } = globalThis as { navigation?: Navigation };

const openingModals = new Set<string>();


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

const ignoreSkippedTransition = (): undefined => undefined;

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

const setMorph = (root: HTMLElement, active: boolean): void => {
  root.style.viewTransitionName = active ? MORPH_NAME : "";
  for (const el of root.querySelectorAll<HTMLElement>("[data-morph]")) {
    el.style.viewTransitionName = active ? `morph-${el.dataset.morph}` : "";
  }
};

const morphTransition = (steps: {
  before: () => void;
  settle: () => void;
  swap: () => void;
}): Promise<void> => {
  steps.before();
  const transition = startViewTransition(steps.swap);
  if (!transition) {
    steps.settle();
    return Promise.resolve();
  }
  return transition.finished
    .catch(ignoreSkippedTransition)
    .finally(steps.settle);
};

const dismissDialog = (dialog: HTMLDialogElement): void => {
  if (!dialog.open) return;
  if (prefersReducedMotion()) {
    dialog.close();
    return;
  }
  startViewTransition(() => {
    dialog.close();
  })?.finished.catch(ignoreSkippedTransition);
};

const openModal = async (
  id: string,
  { animate = true, replaceHistory = false, updateUrl = true } = {},
): Promise<void> => {
  const dialog = getDialog(id);
  let morphPromise: Promise<void> | null = null;
  if (!dialog.open && !openingModals.has(id)) {
    const card = sessionCardForModal(id);
    if (animate && canMorph(card)) {
      openingModals.add(id);
      morphPromise = morphTransition({
        before: () => {
          card.classList.add("morph-source");
          setMorph(card, true);
        },
        settle: () => {
          openingModals.delete(id);
          card.classList.remove("morph-source");
          setMorph(dialog, false);
          card.style.transition = "";
        },
        swap: () => {
          setMorph(card, false);
          card.style.transition = "none";
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

  if (morphPromise) await morphPromise;
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

    const current = new URLSearchParams(globalThis.location.search).get(
      linkable.paramName,
    );
    if (current === linkable.paramValue) {
      updateQueryParam(linkable.paramName, null, { replaceHistory });
    }
  }
};

const syncModalsFromUrl = (): void => {
  if (openingModals.size > 0) return;

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
        void openModal(modalId, { animate: false, updateUrl: false });
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

      e.intercept({
        focusReset: "manual",
        async handler() {
          await openModal(modalId, { updateUrl: false });
        },
        scroll: "manual",
      });
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
      void openModal(modalId);
    });
  }
};

if (!navigation) setupFallbackLinkHandlers();

export { closeModal, openModal };
