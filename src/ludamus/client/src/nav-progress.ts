// Top-edge loading bar (nprogress-style) for the panel. Big events can take a
// while to render server-side; between clicking a link and the new page
// arriving the old page just sits there, so organizers click again. The bar
// appears once a navigation or htmx request outlives a short delay, trickles
// toward 90%, and completes when the response lands. Full-page navigations
// never report "done" — the bar dies with the DOM when the new page replaces
// it, which is exactly when the wait is over.

const SHOW_DELAY_MS = 180; // fast responses never see the bar
const TRICKLE_MS = 250;
// A cancelled navigation (dialog dismissed, download, htmx error path that
// skips afterRequest) never completes; don't let the bar run forever.
const FAILSAFE_MS = 30_000;

const reducedMotion = globalThis.matchMedia("(prefers-reduced-motion: reduce)");

let bar: HTMLElement | null = null;
let pending = 0;
let progress = 0;
let showTimer: ReturnType<typeof setTimeout> | undefined;
let trickleTimer: ReturnType<typeof setInterval> | undefined;
let failsafeTimer: ReturnType<typeof setTimeout> | undefined;
let hideTimer: ReturnType<typeof setTimeout> | undefined;

const render = (): void => {
  if (bar) bar.style.transform = `scaleX(${progress})`;
};

const show = (): void => {
  bar = document.createElement("div");
  bar.setAttribute("aria-hidden", "true");
  Object.assign(bar.style, {
    background: "var(--color-primary)",
    height: "3px",
    inset: "0 0 auto 0",
    pointerEvents: "none",
    position: "fixed",
    transform: "scaleX(0)",
    transformOrigin: "left",
    transition: reducedMotion.matches
      ? "opacity 200ms ease"
      : "transform 200ms ease, opacity 200ms ease",
    // Above the panel sidebar (z-50) and any sticky header.
    zIndex: "9999",
  });
  document.body.append(bar);
  // Reduced motion still deserves feedback: a static partial bar, no trickle.
  progress = reducedMotion.matches ? 0.7 : 0.15;
  requestAnimationFrame(render);
  if (!reducedMotion.matches) {
    trickleTimer = setInterval(() => {
      progress += (0.9 - progress) * (0.05 + Math.random() * 0.1);
      render();
    }, TRICKLE_MS);
  }
};

const reset = (): void => {
  clearTimeout(showTimer);
  clearInterval(trickleTimer);
  clearTimeout(failsafeTimer);
  clearTimeout(hideTimer);
  bar?.remove();
  bar = null;
  pending = 0;
  progress = 0;
};

const start = (): void => {
  pending += 1;
  if (pending > 1) return;
  showTimer = setTimeout(show, SHOW_DELAY_MS);
  failsafeTimer = setTimeout(reset, FAILSAFE_MS);
};

const done = (): void => {
  pending = Math.max(0, pending - 1);
  if (pending > 0) return;
  if (!bar) {
    reset();
    return;
  }
  // Detach the finished bar before the fade so a navigation that starts
  // mid-fade gets a fresh bar instead of having its own removed from under it.
  const finished = bar;
  bar = null;
  reset();
  finished.style.transform = "scaleX(1)";
  hideTimer = setTimeout(() => {
    finished.style.opacity = "0";
    hideTimer = setTimeout(() => finished.remove(), 250);
  }, 150);
};

// Full-page navigations: same-origin left-clicks and plain form submits.
// Bubble phase so anything that intercepts first (confirm dialogs, htmx,
// modal openers) has already called preventDefault by the time we look.
document.addEventListener("click", (event) => {
  if (event.defaultPrevented || event.button !== 0) return;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const { target } = event;
  if (!(target instanceof Element)) return;
  const link = target.closest("a[href]");
  if (!(link instanceof HTMLAnchorElement)) return;
  if ((link.target && link.target !== "_self") || link.hasAttribute("download")) return;
  // htmx-driven links report through htmx:beforeRequest instead.
  if (link.closest("[hx-get],[hx-post],[hx-boost]")) return;
  const url = new URL(link.href, globalThis.location.href);
  if (url.origin !== globalThis.location.origin) return;
  const samePage =
    url.pathname === globalThis.location.pathname && url.search === globalThis.location.search;
  if (samePage && url.hash) return;
  start();
});

document.addEventListener("submit", (event) => {
  if (event.defaultPrevented) return;
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  if (form.target && form.target !== "_self") return;
  if (form.closest("[hx-get],[hx-post],[hx-put],[hx-patch],[hx-delete],[hx-boost]")) return;
  start();
});

// A bfcache restore brings the old DOM back, running bar included.
globalThis.addEventListener("pageshow", (event) => {
  if (event.persisted) reset();
});

// htmx swaps (timetable panes, live filters). Requests wired to a local
// hx-indicator spinner already show feedback next to the control; the top bar
// covers the rest.
const htmxSource = (event: Event): Element | null => {
  const { detail } = event as CustomEvent<{ elt?: unknown }>;
  return detail?.elt instanceof Element ? detail.elt : null;
};

document.addEventListener("htmx:beforeRequest", (event) => {
  if (htmxSource(event)?.closest("[hx-indicator]")) return;
  start();
});

document.addEventListener("htmx:afterRequest", (event) => {
  if (htmxSource(event)?.closest("[hx-indicator]")) return;
  done();
});
