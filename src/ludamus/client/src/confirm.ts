// data-confirm: a styled replacement for native confirm() on destructive
// actions. Put `data-confirm="<message>"` on a <form> or an <a href> and the
// action is gated behind the shared #confirm-dialog modal (see
// components/confirm-dialog.html). `data-confirm-action` optionally overrides
// the accept button label. With no #confirm-dialog on the page, falls back to
// native confirm() so the action is never silently let through.
//
// This module only consumes modal.ts's public API; modal.ts knows nothing
// about it.

import { closeModal, openModal } from "./modal";

const CONFIRM_DIALOG_ID = "confirm-dialog";

let pendingConfirm: (() => void) | null = null;

const getConfirmDialog = (): HTMLDialogElement | null => {
  const element = document.getElementById(CONFIRM_DIALOG_ID);
  return element instanceof HTMLDialogElement ? element : null;
};

interface ConfirmOptions {
  title?: string | null;
  variant?: string | null;
}

export const requestConfirm = (
  message: string,
  acceptLabel: string | null,
  run: () => void,
  options: ConfirmOptions = {},
): void => {
  const text = message
    .replaceAll(String.raw`\n`, "\n")
    .split("\n")
    .map((line) => line.replace(/ (\S+)$/u, `${String.fromCodePoint(160)}$1`))
    .join("\n");

  const dialog = getConfirmDialog();
  if (!dialog) {
    if (globalThis.confirm(text)) run();
    return;
  }

  const messageEl = dialog.querySelector("[data-confirm-message]");
  if (messageEl) messageEl.textContent = text;

  const titleEl = dialog.querySelector<HTMLElement>("[data-confirm-title]");
  if (titleEl) {
    titleEl.dataset.defaultTitle ??= (titleEl.textContent ?? "").trim();
    titleEl.textContent = options.title || titleEl.dataset.defaultTitle;
  }

  const primary = options.variant === "primary";

  const acceptEl = dialog.querySelector<HTMLElement>("[data-confirm-accept]");
  if (acceptEl) {
    acceptEl.dataset.defaultLabel ??= (acceptEl.textContent ?? "").trim();
    acceptEl.textContent = acceptLabel || acceptEl.dataset.defaultLabel;
    acceptEl.classList.toggle("btn-primary", primary);
    acceptEl.classList.toggle("btn-danger", !primary);
  }

  const iconEl = dialog.querySelector<HTMLElement>("[data-confirm-icon]");
  if (iconEl) {
    iconEl.classList.toggle("text-primary", primary);
    iconEl.classList.toggle("text-danger", !primary);
  }

  pendingConfirm = run;
  openModal(CONFIRM_DIALOG_ID, { updateUrl: false });
};

// Forms reach our submit listener twice: once intercepted, then again after
// requestSubmit() once confirmed. The WeakSet marks the second pass.
const confirmedForms = new WeakSet<HTMLFormElement>();

document.addEventListener(
  "submit",
  (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;

    const message = form.dataset.confirm;
    if (!message) return;

    if (confirmedForms.has(form)) {
      confirmedForms.delete(form);
      return;
    }

    event.preventDefault();
    const submitter = event instanceof SubmitEvent ? event.submitter : null;
    requestConfirm(
      message,
      form.dataset.confirmAction ?? null,
      () => {
        confirmedForms.add(form);
        form.requestSubmit(submitter);
      },
      { title: form.dataset.confirmTitle, variant: form.dataset.confirmVariant },
    );
  },
  true,
);

document.addEventListener(
  "click",
  (event) => {
    const { target } = event;
    if (!(target instanceof Element)) return;

    const link = target.closest("a[data-confirm]");
    if (!(link instanceof HTMLAnchorElement)) return;

    const message = link.dataset.confirm;
    if (!message) return;

    event.preventDefault();
    requestConfirm(
      message,
      link.dataset.confirmAction ?? null,
      () => {
        globalThis.location.assign(link.href);
      },
      { title: link.dataset.confirmTitle, variant: link.dataset.confirmVariant },
    );
  },
  true,
);

document.addEventListener("click", (event) => {
  const { target } = event;
  if (!(target instanceof Element)) return;
  if (!target.closest("[data-confirm-accept]")) return;

  const confirmed = pendingConfirm;
  pendingConfirm = null;
  closeModal(CONFIRM_DIALOG_ID, { updateUrl: false });
  confirmed?.();
});

// Escape, backdrop click or the Cancel trigger all dismiss the action.
getConfirmDialog()?.addEventListener("close", () => {
  pendingConfirm = null;
});
