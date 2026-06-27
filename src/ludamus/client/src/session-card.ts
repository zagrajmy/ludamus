// Small interactions for session cards and their detail modals on the event
// page: copy-to-clipboard for Discord handles and numbering waiting-list
// positions.

const COPY_FEEDBACK_MS = 2000;

interface CopyFeedback {
  className: string;
  html: string;
  timer: number;
}
const activeFeedback = new WeakMap<HTMLElement, CopyFeedback>();

// Briefly swap the button's content/style, then restore it. Re-entrant-safe: a
// second click while feedback is still showing reuses the saved originals and
// resets the timer, so the transient state can never be captured as the
// baseline and the button can't get stranded in the success/error look.
const flashCopyFeedback = (button: HTMLElement, className: string, html?: string): void => {
  const existing = activeFeedback.get(button);
  const original = existing ?? {
    className: button.className,
    html: button.innerHTML,
  };
  if (existing) globalThis.clearTimeout(existing.timer);
  button.innerHTML = html ?? original.html;
  button.className = className;
  const timer = globalThis.setTimeout(() => {
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

  // `navigator.clipboard` is undefined in insecure contexts; calling writeText
  // there throws synchronously and would bypass the .catch below.
  if (!navigator.clipboard?.writeText) {
    console.error("Clipboard API unavailable");
    flashCopyFeedback(button, "btn btn-danger p-1 copy-discord");
    return;
  }

  navigator.clipboard
    .writeText(text)
    .then(() => flashCopyFeedback(button, "btn bg-success text-white p-1 copy-discord", "✓"))
    .catch((error: unknown) => {
      console.error("Copy failed:", error);
      flashCopyFeedback(button, "btn btn-danger p-1 copy-discord");
    });
});

// Number waiting list positions within each tab panel.
for (const tabPane of document.querySelectorAll<HTMLElement>(".tab-panel")) {
  let position = 1;
  for (const badge of tabPane.querySelectorAll<HTMLElement>(
    ".waiting-list-row .waiting-position",
  )) {
    badge.textContent = String(position++);
  }
}
