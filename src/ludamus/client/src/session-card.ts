// Small interactions for session cards and their detail modals on the event
// page: copy-to-clipboard for Discord handles, keeping enrollment buttons from
// opening the card, and numbering waiting-list positions.

const COPY_FEEDBACK_MS = 2000;

// Event delegation so it works with htmx-loaded content too.
document.addEventListener("click", (e) => {
  const target = e.target as Element | null;
  const button = target?.closest<HTMLElement>(".copy-discord");
  if (!button) return;

  const text = button.dataset.discord;
  if (!text) return;

  navigator.clipboard
    .writeText(text)
    .then(() => {
      const originalHTML = button.innerHTML;
      const originalClasses = button.className;
      button.innerHTML = "✓";
      button.className = "btn bg-success text-white p-1 copy-discord";
      window.setTimeout(() => {
        button.innerHTML = originalHTML;
        button.className = originalClasses;
      }, COPY_FEEDBACK_MS);
    })
    .catch((err: unknown) => {
      console.error("Copy failed:", err);
      const originalClasses = button.className;
      button.className = "btn btn-danger p-1 copy-discord";
      window.setTimeout(() => {
        button.className = originalClasses;
      }, COPY_FEEDBACK_MS);
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
