// Session bookmarks on the compact event schedule. A tap on a row's bookmark
// button optimistically flips the icon + `data-bookmarked` (so the "Bookmarked"
// filter stays truthful) and POSTs the toggle; a failed request reverts.
//
// Config rides on the .compact-schedule root: data-csrf and
// data-bookmark-url-template (a reverse()d URL with a `0` id placeholder).

const root = document.querySelector<HTMLElement>(".compact-schedule");

const BOOKMARKED_COLOR = ["text-coral-600", "dark:text-coral-400"];

// The template renders `.../session/0/bookmark/`; swap the placeholder segment
// for the real id rather than string-concatenating a path.
const bookmarkUrl = (template: string, sessionId: string): string =>
  template.replace(/0\/bookmark\/?$/, `${sessionId}/bookmark/`);

// Renders one authoritative state; the caller owns which count to show — the
// optimistic ±1 guess, the server's fresh total, or the exact pre-flip number
// on revert.
const paint = (button: HTMLElement, bookmarked: boolean, count: number): void => {
  const countEl = button.querySelector<HTMLElement>(".bookmark-count");
  if (countEl) {
    countEl.textContent = String(count);
    countEl.classList.toggle("hidden", count === 0);
  }
  button.setAttribute("aria-pressed", String(bookmarked));
  button.classList.toggle(BOOKMARKED_COLOR[0], bookmarked);
  button.classList.toggle(BOOKMARKED_COLOR[1], bookmarked);
  button.querySelector(".bookmark-icon-outline")?.classList.toggle("hidden", bookmarked);
  button.querySelector(".bookmark-icon-solid")?.classList.toggle("hidden", !bookmarked);
  const card = button.closest<HTMLElement>(".session");
  if (card) card.dataset.bookmarked = String(bookmarked);
};

// One request per button at a time: a rapid double-click would otherwise fire
// two POSTs whose out-of-order responses can desync the icon from the server.
const inFlight = new WeakSet<HTMLElement>();

const toggleBookmark = async (button: HTMLElement): Promise<void> => {
  if (!root || inFlight.has(button)) return;
  const { sessionId } = button.dataset;
  const template = root.dataset.bookmarkUrlTemplate;
  if (!sessionId || !template) return;

  const previous = button.getAttribute("aria-pressed") === "true";
  const previousCount = Number(button.querySelector(".bookmark-count")?.textContent ?? 0);
  inFlight.add(button);
  paint(button, !previous, previousCount + (previous ? -1 : 1)); // Optimistic flip.
  try {
    const response = await fetch(bookmarkUrl(template, sessionId), {
      headers: { "X-CSRFToken": root.dataset.csrf ?? "" },
      method: "POST",
      // A stalled request must not hold the in-flight guard forever.
      signal: AbortSignal.timeout(8000),
    });
    if (!response.ok) throw new Error(`Bookmark toggle failed: ${response.status}`);
    const data: unknown = await response.json();
    if (
      typeof data !== "object" ||
      data === null ||
      typeof (data as Record<string, unknown>).bookmarked !== "boolean" ||
      typeof (data as Record<string, unknown>).count !== "number"
    ) {
      throw new TypeError("Bookmark toggle: unexpected response");
    }
    const { bookmarked, count } = data as { bookmarked: boolean; count: number };
    paint(button, bookmarked, count);
  } catch (error) {
    paint(button, previous, previousCount); // Revert the optimistic flip.
    console.error(error);
  } finally {
    inFlight.delete(button);
  }
};

if (root) {
  document.addEventListener("click", (event) => {
    const button = (event.target as Element | null)?.closest<HTMLElement>(".bookmark-toggle");
    if (button) void toggleBookmark(button);
  });
}
