// Site-wide delegated handlers for the declarative attributes that replaced
// inline `onclick`/`onchange`/`onsubmit`: those attributes are inert under the
// enforcing CSP, because a nonce covers `<script>` *elements* and never
// event-handler attributes. Loaded from base.html, so shared components can
// count on it being there; the backoffice-only chrome lives in panel-chrome.ts.
// Model: src/copy.ts.

const setDisplay = (id: string | undefined, display: string): void => {
  const node = id ? document.getElementById(id) : null;
  if (node) node.style.display = display;
};

// Swap two sibling panes — the inline display/edit toggles on the companion
// list. Both ids are optional so a control can only reveal, or only hide.
const swapVisibility = (el: HTMLElement): void => {
  setDisplay(el.dataset.hide, "none");
  setDisplay(el.dataset.show, "block");
};

const syncExpandedRequired = (box: HTMLInputElement): void => {
  box.setAttribute("aria-expanded", box.checked ? "true" : "false");
  const id = box.dataset.requiredTarget;
  const field = id ? document.getElementById(id) : null;
  if (!field) return;
  if (box.checked) field.setAttribute("aria-required", "true");
  else field.removeAttribute("aria-required");
};

document.addEventListener("click", (e) => {
  const el = (e.target as Element | null)?.closest<HTMLElement>("[data-action]");
  if (!el) return;
  switch (el.dataset.action) {
    case "history-back":
      globalThis.history.back();
      break;
    case "print":
      globalThis.print();
      break;
    case "swap-visibility":
      swapVisibility(el);
      break;
    default:
      break;
  }
});

document.addEventListener("change", (e) => {
  const el = (e.target as Element | null)?.closest<HTMLElement>("[data-action]");
  if (!el) return;
  switch (el.dataset.action) {
    case "submit-form":
      (el as HTMLInputElement).form?.requestSubmit();
      break;
    case "sync-expanded-required":
      syncExpandedRequired(el as HTMLInputElement);
      break;
    default:
      break;
  }
});

// Double-submit guard for `form[data-submit-once]`: disable the submit button
// as the submission starts, so an impatient second click can't create a second
// row. Nothing re-enables it — the response is a redirect either way.
document.addEventListener("submit", (e) => {
  const form = e.target as HTMLFormElement;
  if (!form.matches("[data-submit-once]")) return;
  const button = form.querySelector<HTMLButtonElement>('button[type="submit"]');
  if (button) button.disabled = true;
});
