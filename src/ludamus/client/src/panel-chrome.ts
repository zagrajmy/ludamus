// Panel chrome — delegated listeners for the backoffice sidebar/header,
// replacing inline `hx-on:` attributes so CSP can drop `'unsafe-eval'`
// (htmx evaluates `hx-on:*` bodies via `Function`, which needs it). One
// document-level listener per event type resolves `[data-action]` on the
// clicked/changed element, so every control stays declarative markup.
// Panel-only, loaded from panel/base.html: actions used by shared components
// or public pages belong in actions.ts, which base.html always loads.
// Model: src/copy.ts. htmx's ambient type lives in htmx.d.ts.

const toggleSidebar = (): void => {
  document.getElementById("sidebar")?.classList.toggle("-translate-x-full");
  document.getElementById("sidebarOverlay")?.classList.toggle("hidden");
};

const toggleFold = (): void => {
  const html = document.documentElement;
  const folded = html.toggleAttribute("data-folded");
  try {
    localStorage.setItem("panel-sidebar-folded", folded ? "1" : "0");
  } catch {
    // Storage unavailable (private mode, disabled) — folding still works
    // for this page load, it just won't persist.
  }
};

const categoryOf = (el: HTMLElement): string | undefined =>
  el.closest<HTMLElement>("[data-cat]")?.dataset.cat;

// `catc-<cat>` on <html> is the *collapsed* marker, so aria-expanded is its
// negation. Stated once, so the toggle and the on-load sync cannot drift.
const setExpanded = (header: HTMLElement, cat: string): void => {
  const collapsed = document.documentElement.classList.contains(`catc-${cat}`);
  header.setAttribute("aria-expanded", String(!collapsed));
};

const toggleCategory = (el: HTMLElement): void => {
  const cat = categoryOf(el);
  if (!cat) return;
  const collapsed = document.documentElement.classList.toggle(`catc-${cat}`);
  setExpanded(el, cat);
  try {
    localStorage.setItem(`panel-cat-${cat}`, collapsed ? "1" : "0");
  } catch {
    // Storage unavailable — collapse state still works for this page load.
  }
};

// The head script restores the collapsed set before paint, but the sidebar does
// not exist yet at that point, so the headers ship as aria-expanded="true" and
// are reconciled here. Module scope is deliberate: `{% vite_asset %}` emits
// `type="module"`, which is deferred, so the DOM is parsed — waiting for
// DOMContentLoaded would only widen the window in which the attribute lies.
const syncCategoryHeaders = (): void => {
  for (const header of document.querySelectorAll<HTMLElement>(
    '.sidebar-cat-header[data-action="toggle-category"]',
  )) {
    const cat = categoryOf(header);
    if (cat) setExpanded(header, cat);
  }
};

const switchEvent = (select: HTMLSelectElement): void => {
  const url = select.selectedOptions[0]?.dataset.url;
  if (url) globalThis.location.assign(url);
};

document.addEventListener("click", (e) => {
  const el = (e.target as Element | null)?.closest<HTMLElement>("[data-action]");
  if (!el) return;
  switch (el.dataset.action) {
    case "toggle-category":
      toggleCategory(el);
      break;
    case "toggle-fold":
      toggleFold();
      break;
    case "toggle-sidebar":
      toggleSidebar();
      break;
    default:
      break;
  }
});

document.addEventListener("change", (e) => {
  const el = (e.target as Element | null)?.closest<HTMLElement>("[data-action]");
  if (!el) return;
  switch (el.dataset.action) {
    case "switch-event":
      switchEvent(el as HTMLSelectElement);
      break;
    default:
      break;
  }
});

// Shared "refresh a pane after a successful htmx request" handler for
// forms/buttons carrying data-refresh-url/data-refresh-target.
document.body.addEventListener("htmx:afterRequest", (e) => {
  const evt = e as CustomEvent<{ successful?: boolean }>;
  const el = (e.target as Element | null)?.closest<HTMLElement>("[data-refresh-url]");
  if (!el || !evt.detail.successful) return;
  const url = el.dataset.refreshUrl;
  const target = el.dataset.refreshTarget;
  if (!url || !target) return;
  htmx.ajax("GET", url, { swap: "outerHTML", target });
});

syncCategoryHeaders();
