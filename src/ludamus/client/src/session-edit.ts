// In-place session editing inside the detail dialog: optimistic switch to the
// edit form on click, rolled back with a message if loading the form fails.

const EDIT_ERROR_TIMEOUT_MS = 6000;

const setSessionEditMode = (
  dialog: HTMLElement | null,
  editing: boolean,
): void => {
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
  alert.setAttribute("data-edit-error", "");
  alert.setAttribute("role", "alert");
  alert.className = "mx-6 mt-4 alert alert-danger text-sm shrink-0";
  alert.textContent = dialog.dataset.editErrorLabel ?? "";
  tabs.parentNode?.insertBefore(alert, tabs);
  window.setTimeout(() => alert.remove(), EDIT_ERROR_TIMEOUT_MS);
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

// After the form loads: focus the title; reset the "Saved" button as soon as
// the facilitator edits again so the confirmation stays honest.
document.body.addEventListener("htmx:afterSwap", (e) => {
  const root = e.target;
  if (!(root instanceof Element)) return;
  const forms = root.matches('form[id$="-edit-form"]')
    ? [root]
    : [...root.querySelectorAll('form[id$="-edit-form"]')];
  forms.forEach((form) => {
    const save = form.querySelector<HTMLElement>("[data-edit-save]");
    if (form.hasAttribute("data-just-saved")) {
      form.addEventListener(
        "input",
        () => {
          if (!save) return;
          save.classList.remove("bg-success", "text-white");
          save.classList.add("btn-primary");
          save.textContent = save.dataset.saveLabel ?? "";
          form.removeAttribute("data-just-saved");
        },
        { once: true },
      );
    } else {
      form.querySelector<HTMLElement>('[name="title"]')?.focus();
    }
  });
});

// Restore the read view if a session dialog is closed while editing, so
// reopening it never lands in a stale edit state.
document
  .querySelectorAll<HTMLDialogElement>('dialog[id^="session-"]')
  .forEach((dialog) => {
    dialog.addEventListener("close", () => setSessionEditMode(dialog, false));
  });
