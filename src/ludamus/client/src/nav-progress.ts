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

// Elements htmx drives itself — they report through htmx:beforeRequest, so
// the click/submit listeners must not also start the bar for them.
const HX_DRIVEN = "[hx-get],[hx-post],[hx-put],[hx-patch],[hx-delete],[hx-boost]";

let bar: HTMLElement | null = null;
let pending = 0;
let progress = 0;
let showTimer: ReturnType<typeof setTimeout> | undefined;
let trickleTimer: ReturnType<typeof setInterval> | undefined;
let failsafeTimer: ReturnType<typeof setTimeout> | undefined;

const render = (): void => {
  if (bar) bar.style.transform = `scaleX(${progress})`;
};

const show = (): void => {
  bar = document.createElement("div");
  // An indeterminate progressbar (no aria-valuenow): assistive tech learns
  // the page is loading instead of the bar hiding as decoration.
  bar.setAttribute("role", "progressbar");
  bar.setAttribute(
    "aria-label",
    document.querySelector('meta[name="nav-progress-label"]')?.getAttribute("content") ??
      "Page loading",
  );
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
  // Detach the finished bar before the fade so a navigation that starts
  // mid-fade gets a fresh bar instead of having its own removed from under
  // it. The fade timers are local closures over the detached element — a
  // later reset() clearing module timers must not cancel its cleanup.
  const finished = bar;
  bar = null;
  reset();
  if (!finished) return;
  finished.style.transform = "scaleX(1)";
  setTimeout(() => {
    finished.style.opacity = "0";
    setTimeout(() => finished.remove(), 250);
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
  if (link.closest(HX_DRIVEN)) return;
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
  if (form.closest(HX_DRIVEN)) return;
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
