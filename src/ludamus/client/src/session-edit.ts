// In-place session editing inside the detail dialog: optimistic switch to the
// edit form on click, rolled back with a message if loading the form fails.

const EDIT_ERROR_TIMEOUT_MS = 6000;

const setSessionEditMode = (dialog: HTMLElement | null, editing: boolean): void => {
  if (!dialog) return;
  const tabs = dialog.querySelector<HTMLElement>("[data-session-tabs]");
  const editform = dialog.querySelector<HTMLElement>('[id$="-editform"]');
  const footer = dialog.querySelector<HTMLElement>("[data-session-footer]");
  if (tabs) tabs.hidden = editing;
  if (footer) footer.hidden = editing;
  if (editform) {
    editform.hidden = !editing;
    if (!editing) editform.innerHTML = "";
  }
  if (editing) dialog.querySelector("[data-edit-error]")?.remove();
};

const showSessionEditError = (dialog: HTMLElement | null): void => {
  const tabs = dialog?.querySelector<HTMLElement>("[data-session-tabs]");
  if (!dialog || !tabs || dialog.querySelector("[data-edit-error]")) return;
  const alert = document.createElement("div");
  alert.dataset.editError = "";
  alert.setAttribute("role", "alert");
  alert.className = "mx-6 mt-4 alert alert-danger text-sm shrink-0";
  alert.textContent = dialog.dataset.editErrorLabel ?? "";
  tabs.parentNode?.insertBefore(alert, tabs);
  globalThis.setTimeout(() => alert.remove(), EDIT_ERROR_TIMEOUT_MS);
};

document.addEventListener("click", (e) => {
  const target = e.target as Element | null;
  const openBtn = target?.closest("[data-edit-open]");
  if (openBtn) {
    setSessionEditMode(openBtn.closest("dialog"), true);
    return;
  }
  const cancelBtn = target?.closest("[data-edit-cancel]");
  if (cancelBtn) setSessionEditMode(cancelBtn.closest("dialog"), false);
});

const rollbackSessionEdit = (e: Event): void => {
  const elt = (e as CustomEvent<{ elt?: unknown }>).detail?.elt;
  if (!(elt instanceof Element) || !elt.matches("[data-edit-open]")) return;
  const dialog = elt.closest("dialog");
  setSessionEditMode(dialog, false);
  showSessionEditError(dialog);
};
document.body.addEventListener("htmx:responseError", rollbackSessionEdit);
document.body.addEventListener("htmx:sendError", rollbackSessionEdit);

// After the form loads: focus the title.
document.body.addEventListener("htmx:afterSwap", (e) => {
  const root = e.target;
  if (!(root instanceof Element)) return;
  const form =
    root instanceof HTMLFormElement && root.matches('form[id$="-edit-form"]')
      ? root
      : root.querySelector<HTMLFormElement>('form[id$="-edit-form"]');
  form?.querySelector<HTMLElement>('[name="title"]')?.focus();
});

// Swap the session's card for the page's fresh one, so the board shows the
// edit the moment the dialog is gone. Through htmx, so the new card is wired
// like any swapped-in card (modal.ts binds its link on htmx:afterSwap).
// A session past the day's turnover is drawn once per day it touches, every
// piece under its id; each is swapped for the piece with its own start, or
// one fetch would put both new pieces where the first old one stood.
const refreshSessionCard = (sessionId: string): void => {
  const key = `[data-session-card="${sessionId}"]`;
  for (const card of document.querySelectorAll<HTMLElement>(key)) {
    const start = card.querySelector<HTMLElement>("[data-start]")?.dataset.start;
    const selector = start ? `${key}:has([data-start="${start}"])` : key;
    htmx.ajax("GET", globalThis.location.href, {
      select: selector,
      swap: "outerHTML",
      target: selector,
    });
  }
};

// A save answers with the session-saved event and no content: close the
// dialog and drop it, so the next open fetches it fresh, then refresh the
// session's cards.
document.body.addEventListener("session-saved", (e) => {
  const sessionId = String((e as CustomEvent<{ id?: number }>).detail?.id ?? "");
  const dialog = document.getElementById(`session-${sessionId}`);
  if (!(dialog instanceof HTMLDialogElement)) return;
  dialog.addEventListener(
    "close",
    () => {
      dialog.remove();
      refreshSessionCard(sessionId);
    },
    { once: true },
  );
  dialog.querySelector<HTMLElement>("[data-modal-close]")?.click();
});

// Restore the read view if a session dialog is closed while editing, so
// reopening it never lands in a stale edit state.
for (const dialog of document.querySelectorAll<HTMLDialogElement>('dialog[id^="session-"]')) {
  dialog.addEventListener("close", () => setSessionEditMode(dialog, false));
}
