// Small interactions for session cards and their detail modals on the event
// page: copy-to-clipboard for Discord handles, keeping enrollment buttons from
// opening the card, and numbering waiting-list positions.

const COPY_FEEDBACK_MS = 2000;

interface CopyFeedback {
  timer: number;
  html: string;
  className: string;
}
const activeFeedback = new WeakMap<HTMLElement, CopyFeedback>();

// Briefly swap the button's content/style, then restore it. Re-entrant-safe: a
// second click while feedback is still showing reuses the saved originals and
// resets the timer, so the transient state can never be captured as the
// baseline and the button can't get stranded in the success/error look.
const flashCopyFeedback = (
  button: HTMLElement,
  className: string,
  html?: string,
): void => {
  const existing = activeFeedback.get(button);
  const original = existing ?? {
    html: button.innerHTML,
    className: button.className,
  };
  if (existing) window.clearTimeout(existing.timer);
  button.innerHTML = html ?? original.html;
  button.className = className;
  const timer = window.setTimeout(() => {
    button.innerHTML = original.html;
    button.className = original.className;
    activeFeedback.delete(button);
  }, COPY_FEEDBACK_MS);
  activeFeedback.set(button, { timer, ...original });
};

// Event delegation so it works with htmx-loaded content too.
document.addEventListener("click", (e) => {
  const target = e.target as Element | null;
  const button = target?.closest<HTMLElement>(".copy-discord");
  if (!button) return;

  const text = button.dataset.discord;
  if (!text) return;

  navigator.clipboard
    .writeText(text)
    .then(() =>
      flashCopyFeedback(
        button,
        "btn bg-success text-white p-1 copy-discord",
        "✓",
      ),
    )
    .catch((err: unknown) => {
      console.error("Copy failed:", err);
      flashCopyFeedback(button, "btn btn-danger p-1 copy-discord");
    });
});

// Prevent enrollment buttons from triggering the card click (which opens the
// detail modal).
document
  .querySelectorAll<HTMLElement>(".session-card .btn")
  .forEach((button) => {
    button.addEventListener("click", (e) => e.stopPropagation());
  });

// Number waiting list positions within each tab panel.
document.querySelectorAll<HTMLElement>(".tab-panel").forEach((tabPane) => {
  let position = 1;
  tabPane
    .querySelectorAll<HTMLElement>(".waiting-list-row .waiting-position")
    .forEach((badge) => {
      badge.textContent = String(position++);
    });
});
