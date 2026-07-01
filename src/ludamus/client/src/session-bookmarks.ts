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

const paint = (button: HTMLElement, bookmarked: boolean): void => {
  button.setAttribute("aria-pressed", String(bookmarked));
  button.classList.toggle(BOOKMARKED_COLOR[0], bookmarked);
  button.classList.toggle(BOOKMARKED_COLOR[1], bookmarked);
  button.querySelector(".bookmark-icon-outline")?.classList.toggle("hidden", bookmarked);
  button.querySelector(".bookmark-icon-solid")?.classList.toggle("hidden", !bookmarked);
  const card = button.closest<HTMLElement>(".session-card");
  if (card) card.dataset.bookmarked = String(bookmarked);
};

const toggleBookmark = async (button: HTMLElement): Promise<void> => {
  if (!root) return;
  const { sessionId } = button.dataset;
  const template = root.dataset.bookmarkUrlTemplate;
  if (!sessionId || !template) return;

  const previous = button.getAttribute("aria-pressed") === "true";
  paint(button, !previous); // Optimistic flip.
  try {
    const response = await fetch(bookmarkUrl(template, sessionId), {
      headers: { "X-CSRFToken": root.dataset.csrf ?? "" },
      method: "POST",
    });
    if (!response.ok) throw new Error(`Bookmark toggle failed: ${response.status}`);
    const data: unknown = await response.json();
    if (
      typeof data !== "object" ||
      data === null ||
      typeof (data as Record<string, unknown>).bookmarked !== "boolean"
    ) {
      throw new TypeError("Bookmark toggle: unexpected response");
    }
    paint(button, (data as { bookmarked: boolean }).bookmarked);
  } catch (error) {
    paint(button, previous); // Revert the optimistic flip.
    console.error(error);
  }
};

if (root) {
  document.addEventListener("click", (event) => {
    const button = (event.target as Element | null)?.closest<HTMLElement>(".bookmark-toggle");
    if (button) void toggleBookmark(button);
  });
}
