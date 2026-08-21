// Write-through mirror for client-side state in the query string.
//
// replaceState only, never pushState: a mirrored param is an adjustment of
// the current page, not a place — Back must leave the page (or close a
// modal), never step through filter edits. modal.ts owns push navigations on
// the same URLs; a replace neither fires popstate nor passes its Navigation
// API listener's `navigationType === "push"` guard, so the two can share a
// query string without ever fighting over history entries.

/** Query updates keyed by param name; null or "" deletes the param. */
type SearchParamUpdates = ReadonlyMap<string, string | null>;

const withUpdates = (url: URL, updates: SearchParamUpdates): URL => {
  for (const [name, value] of updates) {
    if (value === null || value === "") url.searchParams.delete(name);
    else url.searchParams.set(name, value);
  }
  return url;
};

/** Mirror `updates` into the address bar, leaving params outside it alone. */
const replaceSearchParams = (updates: SearchParamUpdates): void => {
  const url = withUpdates(new URL(globalThis.location.href), updates);
  if (url.href === globalThis.location.href) return;
  // Keep whatever state the entry carries — htmx and modal.ts both push
  // entries on this page, and a mirror write must not disturb either.
  globalThis.history.replaceState(globalThis.history.state, "", url);
};

/** Apply `updates` to an href so a follow link carries the mirrored state. */
const hrefWithSearchParams = (href: string, updates: SearchParamUpdates): string => {
  const url = withUpdates(new URL(href, globalThis.location.href), updates);
  return url.pathname + url.search + url.hash;
};

export { hrefWithSearchParams, replaceSearchParams, type SearchParamUpdates };
