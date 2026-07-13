// Panel chrome — delegated listeners for the backoffice sidebar/header,
// replacing inline `hx-on:` attributes so CSP can drop `'unsafe-eval'`
// (htmx evaluates `hx-on:*` bodies via `Function`, which needs it). One
// document-level listener per event type resolves `[data-action]` on the
// clicked/changed element, so every control stays declarative markup.
// Model: src/copy.ts.

declare const htmx: {
  ajax: (method: string, url: string, opts: { swap: string; target: string }) => void;
};

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

const toggleCategory = (el: HTMLElement): void => {
  const cat = el.closest<HTMLElement>("[data-cat]")?.dataset.cat;
  if (!cat) return;
  const active = document.documentElement.classList.toggle(`catc-${cat}`);
  try {
    localStorage.setItem(`panel-cat-${cat}`, active ? "1" : "0");
  } catch {
    // Storage unavailable — collapse state still works for this page load.
  }
};

const switchEvent = (select: HTMLSelectElement): void => {
  const url = select.selectedOptions[0]?.dataset.url;
  if (url) globalThis.location.assign(url);
};

const syncExpandedRequired = (box: HTMLInputElement): void => {
  box.setAttribute("aria-expanded", box.checked ? "true" : "false");
  const id = box.dataset.requiredTarget;
  const field = id ? document.getElementById(id) : null;
  if (!field) return;
  if (box.checked) field.setAttribute("aria-required", "true");
  else field.removeAttribute("aria-required");
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
    case "sync-expanded-required":
      syncExpandedRequired(el as HTMLInputElement);
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
