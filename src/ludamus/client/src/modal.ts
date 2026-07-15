/**
 * Addressable modals. A trigger link's first query param is the source of truth
 * for open state, so every modal is shareable, bookmarkable, and closes on Back.
 *
 * Prefer this over an imperative open handler: `syncModalsFromUrl` opens whichever
 * modal matches the URL on load / popstate, `openModal` writes the param, and
 * `closeModal` clears it. Nothing else needs to know a modal exists.
 *
 * @usage
 *   <a href="?invite=5" aria-controls="invite-modal-5" aria-haspopup="dialog">Invite</a>
 *   <dialog id="invite-modal-5" class="modal">…</dialog>
 *
 * To reopen a modal after a failed POST, render the response at that same
 * `?param=value` — point the form's action at it (`action="…?add-companion=1"`)
 * and `syncModalsFromUrl` reopens it on load, errors and all. No server-set flag.
 *
 * Triggers must be same-path query links (`?x=y`), not buttons: the Navigation API
 * interception below only fires for anchor navigations to the current pathname.
 */
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

const isSkippedTransitionError = (error: unknown): boolean =>
  error instanceof DOMException &&
  error.name === "AbortError" &&
  error.message.includes("Transition was skipped");

const ignoreSkippedTransition = (error: unknown): void => {
  if (isSkippedTransitionError(error)) return;
  throw error;
};

const MORPH_NAME = "session-morph";
const CARD_SUPPRESSED = "session-suppressed";
// <html> classes that scope the page-blur keyframes to a morph's lifetime (see
// modal.css). Derived from MORPH_NAME so the prefix relationship is explicit.
const ROOT_MORPH_OPEN = `${MORPH_NAME}-open`;
const ROOT_MORPH_CLOSE = `${MORPH_NAME}-close`;

const sessionCardForModal = (id: string): HTMLElement | null => {
  if (!id.startsWith("session-")) return null;
  const card = document.querySelector(
    `.session[data-session-id="${CSS.escape(id.slice("session-".length))}"]`,
  );
  return card instanceof HTMLElement ? card : null;
};

const suppressSessionCard = (id: string): void => {
  sessionCardForModal(id)?.classList.add(CARD_SUPPRESSED);
};

const releaseSessionCard = (id: string): void => {
  sessionCardForModal(id)?.classList.remove(CARD_SUPPRESSED);
};

const canMorph = (card: HTMLElement | null): card is HTMLElement =>
  card !== null &&
  card.dataset.noMorph === undefined &&
  !prefersReducedMotion() &&
  typeof (document as Document & ViewTransitionDocument).startViewTransition === "function";

const setSubMorph = (root: HTMLElement, active: boolean): void => {
  for (const el of root.querySelectorAll<HTMLElement>("[data-morph]")) {
    el.style.viewTransitionName = active ? `morph-${el.dataset.morph}` : "";
  }
};

const setContainerMorph = (root: HTMLElement, active: boolean): void => {
  root.style.viewTransitionName = active ? MORPH_NAME : "";
};

const setMorph = (root: HTMLElement, active: boolean): void => {
  setContainerMorph(root, active);
  setSubMorph(root, active);
};

const setRootMorph = (className: string, active: boolean): void => {
  document.documentElement.classList.toggle(className, active);
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
  return transition.finished.catch(ignoreSkippedTransition).finally(steps.settle);
};

const dismissDialog = (dialog: HTMLDialogElement): void => {
  if (!dialog.open) return;
  if (prefersReducedMotion()) {
    dialog.close();
    return;
  }
  startViewTransition(() => {
    dialog.close();
  })?.finished.catch((error) => {
    try {
      ignoreSkippedTransition(error);
    } catch (error_) {
      console.error(error_);
    }
  });
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
          setRootMorph(ROOT_MORPH_OPEN, true);
          setMorph(card, true);
        },
        settle: () => {
          setRootMorph(ROOT_MORPH_OPEN, false);
          openingModals.delete(id);
          setMorph(dialog, false);
          card.style.transition = "";
        },
        swap: () => {
          suppressSessionCard(id);
          setMorph(card, false);
          card.style.transition = "none";
          dialog.showModal();
          setMorph(dialog, true);
        },
      });
    } else {
      dialog.showModal();
      suppressSessionCard(id);
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
        before: () => {
          setRootMorph(ROOT_MORPH_CLOSE, true);
          setContainerMorph(dialog, true);
        },
        settle: () => {
          setRootMorph(ROOT_MORPH_CLOSE, false);
          setContainerMorph(card, false);
        },
        swap: () => {
          dialog.close();
          setContainerMorph(dialog, false);
          releaseSessionCard(id);
          setContainerMorph(card, true);
        },
      });
    } else {
      dismissDialog(dialog);
      releaseSessionCard(id);
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

// Session detail modals are fetched on first open instead of pre-rendered
// (a big event has hundreds; rendering them all bloats the page and chokes the
// debug toolbar). The container carries a reverse()d URL with a `0` id
// placeholder; injected dialogs are cached in the DOM so reopen + morph-close
// stay instant.
declare const htmx: { process(el: Element): void };

const SESSION_MODAL_PREFIX = "session-";
const inflightModals = new Map<string, Promise<boolean>>();

const modalContainer = (): HTMLElement | null =>
  document.querySelector<HTMLElement>("[data-session-modal-url]");

const sessionModalUrl = (pk: string): string | null => {
  const template = modalContainer()?.dataset.sessionModalUrl;
  return template ? template.replace(/\/session\/0\//, `/session/${pk}/`) : null;
};

const numberWaitingPositions = (root: ParentNode): void => {
  for (const pane of root.querySelectorAll<HTMLElement>(".tab-panel")) {
    let position = 1;
    for (const badge of pane.querySelectorAll<HTMLElement>(".waiting-list-row .waiting-position")) {
      badge.textContent = String(position++);
    }
  }
};

// Tabs, click-outside and Escape are delegated on document, so injected modals
// get those free. The close (×) button, waiting-list numbering and HTMX binding
// are per-element and must be wired on the fetched fragment.
const wireCloseButtons = (root: ParentNode): void => {
  for (const trigger of root.querySelectorAll("[data-modal-close]")) {
    trigger.addEventListener("touchend", closeFromTrigger, { capture: true });
    trigger.addEventListener("click", closeFromTrigger, { capture: true });
  }
};

const wireInjectedModal = (dialog: HTMLElement): void => {
  wireCloseButtons(dialog);
  numberWaitingPositions(dialog);
  htmx.process(dialog);
};

const fetchModal = async (id: string, url: string): Promise<boolean> => {
  const response = await fetch(url, {
    headers: { "X-Requested-With": "fetch" },
    signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok) throw new Error(`modal ${id}: HTTP ${response.status}`);
  const html = await response.text();
  const template = document.createElement("template");
  template.innerHTML = html.trim();
  const dialog = template.content.firstElementChild;
  if (!(dialog instanceof HTMLElement) || dialog.id !== id) {
    throw new Error(`modal ${id}: unexpected fragment`);
  }
  modalContainer()?.append(dialog);
  wireInjectedModal(dialog);
  return true;
};

/** Ensure the dialog for `id` is in the DOM, fetching it on first use. */
const ensureModalLoaded = async (id: string): Promise<boolean> => {
  if (document.getElementById(id)) return true;
  if (!id.startsWith(SESSION_MODAL_PREFIX)) return false;
  const url = sessionModalUrl(id.slice(SESSION_MODAL_PREFIX.length));
  if (!url) return false;

  let pending = inflightModals.get(id);
  if (!pending) {
    pending = fetchModal(id, url).catch((error: unknown) => {
      console.error(error);
      return false;
    });
    inflightModals.set(id, pending);
    void pending.finally(() => inflightModals.delete(id));
  }
  return pending;
};

const isLazySessionModal = (id: string): boolean =>
  id.startsWith(SESSION_MODAL_PREFIX) && modalContainer() !== null;

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
      !isLazySessionModal(modalId) &&
      !(target instanceof HTMLDialogElement && target.classList.contains("modal"))
    )
      continue;

    const hrefUrl = new URL(href, globalThis.location.href);
    for (const [paramName, paramValue] of hrefUrl.searchParams) {
      if (searchParams.get(paramName) === paramValue) {
        void ensureModalLoaded(modalId).then((ok) => {
          if (ok) void openModal(modalId, { animate: false, updateUrl: false });
        });
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
      if (
        !isLazySessionModal(modalId) &&
        !(target instanceof HTMLDialogElement && target.classList.contains("modal"))
      )
        continue;

      e.intercept({
        focusReset: "manual",
        async handler() {
          if (await ensureModalLoaded(modalId)) {
            await openModal(modalId, { updateUrl: false });
          } else {
            // Lazy fetch failed: fall back to a real navigation to the trigger
            // href. That page's deep-link path retries without re-intercepting,
            // so there is no loop.
            globalThis.location.assign(href);
          }
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
  wireCloseButtons(document);
};

document.addEventListener("click", (event) => {
  const eventTarget = event.target;
  if (!(eventTarget instanceof Element)) return;

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

const setupFallbackLinkHandlers = (): void => {
  for (const link of document.querySelectorAll("a[href][aria-controls]")) {
    const modalId = link.getAttribute("aria-controls");
    const href = link.getAttribute("href");
    if (!modalId || !href) continue;

    const target = document.getElementById(modalId);
    if (
      !isLazySessionModal(modalId) &&
      !(target instanceof HTMLDialogElement && target.classList.contains("modal"))
    )
      continue;

    link.addEventListener("click", (e) => {
      e.preventDefault();
      void ensureModalLoaded(modalId).then((ok) => {
        if (ok) void openModal(modalId);
        else globalThis.location.assign(href);
      });
    });
  }
};

if (!navigation) setupFallbackLinkHandlers();

export { closeModal, openModal };
