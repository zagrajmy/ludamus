// Config rides on the .compact-schedule root: data-csrf and
// data-bookmark-url-template (a reverse()d URL with a `0` id placeholder).

const BOOKMARKED_COLOR = ["text-coral-600", "dark:text-coral-400"];

// The template renders `.../session/0/bookmark/`; swap the placeholder segment
// for the real id rather than string-concatenating a path.
const bookmarkUrl = (template: string, sessionId: string): string =>
  template.replace(/0\/bookmark\/?$/, `${sessionId}/bookmark/`);

const bookmarkButtons = (sessionId: string): HTMLElement[] =>
  [...document.querySelectorAll<HTMLElement>(".bookmark-toggle")].filter(
    (button) => button.dataset.sessionId === sessionId,
  );

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

const paintSession = (sessionId: string, bookmarked: boolean, count: number): void => {
  for (const button of bookmarkButtons(sessionId)) paint(button, bookmarked, count);
  document.dispatchEvent(new CustomEvent("session:bookmark-changed"));
};

// NOTE: the in-flight guard is state, not an affordance. Disabling the button
// would fade it to the :disabled opacity right after the optimistic paint —
// a blink that reads as lag — and would drop keyboard focus mid-toggle.
const inFlight = new Set<string>();

const toggleBookmark = async (button: HTMLElement): Promise<void> => {
  const root = button.closest<HTMLElement>(".compact-schedule");
  const { sessionId } = button.dataset;
  const template = root?.dataset.bookmarkUrlTemplate;
  if (!root || !sessionId || !template || inFlight.has(sessionId)) return;

  const previous = button.getAttribute("aria-pressed") === "true";
  const previousCount = Number(button.querySelector(".bookmark-count")?.textContent ?? 0);
  inFlight.add(sessionId);
  paintSession(sessionId, !previous, previousCount + (previous ? -1 : 1));
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
    paintSession(sessionId, bookmarked, count);
  } catch (error) {
    paintSession(sessionId, previous, previousCount);
    console.error(error);
  } finally {
    inFlight.delete(sessionId);
  }
};

document.addEventListener("click", (event) => {
  const button = (event.target as Element | null)?.closest<HTMLElement>(".bookmark-toggle");
  if (button) void toggleBookmark(button);
});
