// Write-through mirror for client-side state in the query string.
//
// replaceState only, never pushState: a mirrored param is an adjustment of
// the current page, not a place — Back must leave the page (or close a
// modal), never step through filter edits. modal.ts owns push navigations on
// the same URLs; a replace neither fires popstate nor passes its Navigation
// API listener's `navigationType === "push"` guard, so the two can share a
// query string without ever fighting over history entries.
//
// Reserved names, owned by push writers and off-limits to mirrors: `session`
// and `enter-code` (modal.ts trigger links) and the schedule view switcher's
// `view` (an hx-boosted GET). Event-defined names must carry a feature
// prefix (session-filters.ts uses `tag-`) so user data can't collide either.

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

/**
 * Splice `carried` back into the address bar after a committed same-path
 * navigation, keeping every param the destination did not itself set.
 *
 * Trigger hrefs carry only their own param (`?session=5`), so a committed
 * one would silently cost every other feature its params — the mirror, the
 * view switcher's `?view=`. Capture `location.search` before the navigation
 * commits (a Navigation API intercept handler runs after) and call this once
 * the destination URL is in place.
 */
const restoreCarriedSearchParams = (carried: URLSearchParams): void => {
  const url = new URL(globalThis.location.href);
  let restored = false;
  for (const [name, value] of carried) {
    if (url.searchParams.has(name)) continue;
    url.searchParams.set(name, value);
    restored = true;
  }
  if (restored) globalThis.history.replaceState(globalThis.history.state, "", url);
};

// Typed params. A codec is total in both directions: parse turns any raw
// value — a stale share, a hand-edited bogus one — into a value the feature
// can hold, and serialize returns null to mean "drop the param". Binding a
// codec per param keeps the URL and the controls from ever disagreeing about
// what a value means, without routing interactions through the URL.

interface SearchParamCodec<T> {
  parse: (raw: string | null) => T;
  serialize: (value: T) => string | null;
}

const stringParam: SearchParamCodec<string> = {
  parse: (raw) => raw ?? "",
  serialize: (value) => value.trim() || null,
};

/** Presence flag: serialized as "1"; any non-empty raw value parses as on. */
const flagParam: SearchParamCodec<boolean> = {
  parse: (raw) => raw !== null && raw !== "",
  serialize: (value) => (value ? "1" : null),
};

/** Integer within [min, max]; anything else parses to null and drops. */
const intParam = (min: number, max: number): SearchParamCodec<number | null> => ({
  parse: (raw) => {
    const value = Number.parseInt(raw ?? "", 10);
    return Number.isNaN(value) || value < min || value > max ? null : value;
  },
  serialize: (value) => (value === null ? null : String(value)),
});

export {
  flagParam,
  hrefWithSearchParams,
  intParam,
  replaceSearchParams,
  restoreCarriedSearchParams,
  type SearchParamCodec,
  type SearchParamUpdates,
  stringParam,
};
