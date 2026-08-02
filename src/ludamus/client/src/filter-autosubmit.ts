// Live filtering for `form[data-autosubmit]`: the form carries hx-get, so a
// submit becomes a partial swap of the results region. Text fields submit on
// Enter (native submit), blur (change event), or a 1s typing pause; selects
// and checkboxes submit immediately. Degrades without JS — the form keeps its
// visually-hidden submit button and falls back to a full-page GET.
const DEBOUNCE_MS = 1000;

const serialize = (form: HTMLFormElement): string =>
  [...new FormData(form)].map(([key, value]) => `${key}=${String(value)}`).join("&");

// A multi-select popover applies on its own Apply button: auto-submitting per
// tick would reload the page under a user still picking, and its search box is
// a local narrowing control that must never reach the server.
const isSelfApplying = (event: Event): boolean =>
  (event.target as Element | null)?.closest("[data-multiselect-filter]") != null;

for (const form of document.querySelectorAll<HTMLFormElement>("form[data-autosubmit]")) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let lastSubmitted = serialize(form);

  const submit = (): void => {
    const params = serialize(form);
    if (params === lastSubmitted) return;
    lastSubmitted = params;
    form.requestSubmit();
  };

  const schedule = (delay: number): void => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(submit, delay);
  };

  form.addEventListener("change", (event) => {
    if (!isSelfApplying(event)) schedule(0);
  });
  form.addEventListener("input", (event) => {
    if (event.target instanceof HTMLInputElement && !isSelfApplying(event)) {
      schedule(DEBOUNCE_MS);
    }
  });
  form.addEventListener("submit", () => {
    // Enter-key submits bypass `submit()`; sync state so a later blur
    // doesn't re-request the same URL.
    if (timer) clearTimeout(timer);
    lastSubmitted = serialize(form);
  });
}
