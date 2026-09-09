import { pollUntil } from "./snapshot";

// Attribute values arrive escaped. `&amp;` goes last: unescaping it first would
// turn a served `&amp;lt;` (the literal text "&lt;") into "<" -- CodeQL's
// double-unescape, and a name that would never match its device label.
export const decodeEntities = (value: string): string =>
  value
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&quot;", '"')
    .replaceAll("&#x27;", "'")
    .replaceAll("&#39;", "'")
    .replaceAll("&amp;", "&");

// Waits for the page to serve `contains`, then hands back the body. A caller
// that needs a landmark from the markup -- a scrubber slot anchor, the
// accessible name of a control -- reads it here instead of hunting for it with
// gestures, which are the slowest thing either spec can do.
export const fetchReadyPage = async (url: URL, contains: string): Promise<string> => {
  console.log(`Checking local page at ${url.toString()}...`);
  let lastError = "no response";

  // NOTE: bun's fetch sends no Accept-Language, so Django falls back to
  // LANGUAGE_CODE ("pl") and dates render "Sobota" while the en-US simulator's
  // Safari asks for and gets "Saturday". Names read from this HTML would then
  // never match device labels. Pinning "en" aligns the two; if the simulator is
  // ever not English, set-membership finds nothing and the spec fails loudly
  // rather than passing vacuously.
  const headers = { "Accept-Language": "en" };

  const unusable = (): Error =>
    new Error(
      `Local page is not usable at ${url.toString()} (${lastError}). ` +
        "Make sure the e2e server is running and serving the seeded event.",
    );

  const page = await pollUntil<string>(
    async () => {
      let status: number | null = null;
      try {
        // Bounded per request: pollUntil cannot interrupt a pending fetch, so a
        // stalled server would otherwise hold the hook past the window.
        const response = await fetch(url, { headers, signal: AbortSignal.timeout(5000) });
        const text = await response.text();
        if (response.ok && text.includes(contains)) return text;

        status = response.status;
        lastError = `HTTP ${status}; body starts with ${JSON.stringify(text.slice(0, 160))}`;
      } catch (error) {
        lastError = error instanceof Error ? error.message : String(error);
      }
      // A 4xx is a wrong URL or a missing seed, not a server still starting; no
      // amount of polling fixes it.
      if (status !== null && status >= 400 && status < 500) throw unusable();
      return null;
    },
    { timeoutMs: 60000, intervalMs: 1000 },
  );
  if (page === null) throw unusable();
  return page;
};
