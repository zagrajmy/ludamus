// Flash messages (Django `messages`). The markup carries the full intent —
// `data-flash="sticky|transient"`, a `[data-flash-dismiss]` button, and
// role/aria-live — but nothing implemented it. This wires that up: every flash
// is dismissible, and transient ones auto-dismiss after a pause-able delay.
// Exits are reduced-motion-safe.

const AUTO_DISMISS_MS = 5000;
const EXIT_MS = 260;
const EXIT_FALLBACK_MS = EXIT_MS + 100;
const STACK_GAP = 8;
const VISIBLE_TOASTS = 3;

const prefersReducedMotion = (): boolean =>
  globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

const activeFlashes = (region: HTMLElement): HTMLElement[] =>
  Array.from(region.querySelectorAll<HTMLElement>("[data-flash]"), (flash) => flash).filter(
    (flash) => flash.dataset.flashClosing !== "true",
  );

const layoutRegion = (region: HTMLElement): void => {
  const flashes = activeFlashes(region);
  if (flashes.length === 0) {
    region.style.height = "0px";
    return;
  }

  const expanded = region.dataset.flashExpanded === "true";
  for (const flash of flashes) flash.style.height = "";

  const heights = flashes.map((flash) => flash.offsetHeight);
  const frontHeight = heights[0] ?? 0;
  const visibleCount = Math.min(flashes.length, VISIBLE_TOASTS);
  let offset = 0;

  for (const [index, flash] of flashes.entries()) {
    const mounted = flash.dataset.flashMounted === "true";
    const visible = index < VISIBLE_TOASTS;
    const height = heights[index] ?? frontHeight;

    flash.dataset.flashFront = String(index === 0);
    flash.dataset.flashVisible = String(visible);
    flash.dataset.flashExpanded = String(expanded);
    flash.style.zIndex = String(flashes.length - index);

    if (!mounted || !visible) {
      flash.style.height = "";
      flash.style.transform = "";
      continue;
    }

    if (expanded) {
      flash.style.height = `${height}px`;
      flash.style.transform = `translateY(${offset}px) scale(1)`;
      offset += height + STACK_GAP;
    } else if (index === 0) {
      flash.style.height = `${height}px`;
      flash.style.transform = "translateY(0) scale(1)";
    } else {
      flash.style.height = `${frontHeight}px`;
      flash.style.transform = `translateY(${STACK_GAP * index}px) scale(${1 - index * 0.05})`;
    }
  }

  region.style.height = expanded
    ? `${Math.max(0, offset - STACK_GAP)}px`
    : `${frontHeight + STACK_GAP * (visibleCount - 1)}px`;
};

const setExpanded = (region: HTMLElement, expanded: boolean): void => {
  region.dataset.flashExpanded = String(expanded);
  layoutRegion(region);
};

const wireRegion = (region: HTMLElement): void => {
  if (region.dataset.flashStackWired === "true") return;
  region.dataset.flashStackWired = "true";
  region.dataset.flashExpanded = "false";
  region.addEventListener("pointerenter", () => setExpanded(region, true));
  region.addEventListener("pointerleave", () => setExpanded(region, false));
  region.addEventListener("focusin", () => setExpanded(region, true));
  region.addEventListener("focusout", (event) => {
    if (event.relatedTarget instanceof Node && region.contains(event.relatedTarget)) return;
    setExpanded(region, false);
  });
};

const finishRemoval = (flash: HTMLElement): void => {
  const region = flash.closest<HTMLElement>(".flash-region");
  flash.remove();
  if (region) layoutRegion(region);
};

const remove = (flash: HTMLElement): void => {
  if (flash.dataset.flashClosing === "true") return;
  const region = flash.closest<HTMLElement>(".flash-region");
  const wasFront = flash.dataset.flashFront === "true";
  flash.dataset.flashClosing = "true";

  if (region) {
    layoutRegion(region);
    flash.style.transform = wasFront
      ? "translateY(-100%) scale(0.98)"
      : "translateY(40%) scale(0.95)";
  }

  if (prefersReducedMotion()) {
    finishRemoval(flash);
    return;
  }

  let finished = false;
  const finish = (): void => {
    if (finished) return;
    finished = true;
    finishRemoval(flash);
  };
  const onTransitionEnd = (event: TransitionEvent): void => {
    if (event.target !== flash || event.propertyName !== "transform") return;
    flash.removeEventListener("transitionend", onTransitionEnd);
    finish();
  };
  flash.addEventListener("transitionend", onTransitionEnd);
  globalThis.setTimeout(() => {
    flash.removeEventListener("transitionend", onTransitionEnd);
    finish();
  }, EXIT_FALLBACK_MS);
};

const reveal = (flash: HTMLElement): void => {
  const region = flash.closest<HTMLElement>(".flash-region");
  if (region) wireRegion(region);
  flash.dataset.flashMounted = "false";
  if (region) layoutRegion(region);

  if (prefersReducedMotion()) {
    flash.dataset.flashMounted = "true";
    if (region) layoutRegion(region);
    return;
  }

  globalThis.requestAnimationFrame(() => {
    globalThis.requestAnimationFrame(() => {
      flash.dataset.flashMounted = "true";
      if (region) layoutRegion(region);
    });
  });
};

export const initFlash = (flash: HTMLElement): void => {
  if (flash.dataset.flashInitialized === "true") return;
  flash.dataset.flashInitialized = "true";
  reveal(flash);

  const dismiss = flash.querySelector<HTMLElement>("[data-flash-dismiss]");
  dismiss?.addEventListener("click", () => {
    remove(flash);
  });

  if (flash.dataset.flash !== "transient") return;

  let timer: ReturnType<typeof setTimeout> | undefined;
  const start = (): void => {
    timer = setTimeout(() => {
      remove(flash);
    }, AUTO_DISMISS_MS);
  };
  const pause = (): void => {
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
  };

  // Don't yank a message out from under someone who's reading or interacting.
  flash.addEventListener("pointerenter", pause);
  flash.addEventListener("focusin", pause);
  flash.addEventListener("pointerleave", start);
  flash.addEventListener("focusout", start);

  start();
};

const wire = (): void => {
  for (const flash of document.querySelectorAll<HTMLElement>("[data-flash]")) {
    initFlash(flash);
  }
};

// Programmatically raise a sticky error toast, reusing the same markup/behavior
// as server-rendered flashes. The `.flash-region` toaster is only server-
// rendered when there are messages, so create it on <body> (it's position:fixed)
// when a client-side error needs to surface with no region present.
export const pushErrorFlash = (message: string): void => {
  let region = document.querySelector<HTMLElement>(".flash-region");
  if (!region) {
    region = document.createElement("div");
    region.className = "flash-region";
    region.setAttribute("role", "region");
    region.setAttribute("aria-label", document.body.dataset.flashRegionLabel ?? "");
    document.body.append(region);
  }

  const alert = document.createElement("div");
  alert.className = "alert alert-danger backdrop-blur-lg flex items-center";
  alert.dataset.flash = "sticky";
  alert.setAttribute("role", "alert");
  alert.setAttribute("aria-live", "assertive");

  const text = document.createElement("span");
  text.className = "text-sm";
  text.textContent = message;

  const dismiss = document.createElement("button");
  dismiss.type = "button";
  dismiss.dataset.flashDismiss = "";
  dismiss.className =
    "ml-auto pl-3 shrink-0 opacity-70 hover:opacity-100 transition-opacity cursor-pointer";
  dismiss.setAttribute("aria-label", document.body.dataset.flashDismissLabel ?? "");
  dismiss.textContent = "✕";

  alert.append(text, dismiss);
  region.append(alert);
  initFlash(alert);
};

// htmx silently drops non-2xx responses (no swap, no navigation), so a server
// error on an htmx form/component leaves the user with no feedback — exactly
// the "it said it worked but didn't" trap. Surface 5xx and transport failures
// as an error toast. 4xx is left alone: endpoints may return it deliberately
// with their own inline handling.
const SERVER_ERROR_STATUS = 500;

const serverErrorMessage = (): string =>
  document.body.dataset.serverErrorMessage ?? "Something went wrong.";

document.body.addEventListener("htmx:responseError", (event) => {
  const { xhr } = (event as CustomEvent<{ xhr?: XMLHttpRequest }>).detail;
  if (xhr && xhr.status >= SERVER_ERROR_STATUS) pushErrorFlash(serverErrorMessage());
});
document.body.addEventListener("htmx:sendError", () => {
  pushErrorFlash(serverErrorMessage());
});

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", wire);
} else {
  wire();
}
