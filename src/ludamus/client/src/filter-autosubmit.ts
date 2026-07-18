// Live filtering for `form[data-autosubmit]`: submit on change (selects,
// checkboxes) or debounced input (text fields) so filters apply without a
// button. Degrades without JS — the form keeps its visually-hidden submit.
const DEBOUNCE_MS = 450;

for (const form of document.querySelectorAll<HTMLFormElement>("form[data-autosubmit]")) {
  let timer: ReturnType<typeof setTimeout> | undefined;

  const submit = (): void => {
    form.setAttribute("aria-busy", "true");
    form.querySelector("[data-autosubmit-spinner]")?.classList.remove("hidden");
    form.submit();
  };

  const schedule = (delay: number): void => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(submit, delay);
  };

  form.addEventListener("change", () => schedule(0));
  form.addEventListener("input", (e) => {
    if ((e.target as HTMLElement).tagName === "INPUT") schedule(DEBOUNCE_MS);
  });
}
