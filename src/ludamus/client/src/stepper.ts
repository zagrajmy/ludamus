// − / + buttons for any `[data-stepper]` number field. One delegated listener
// keeps every stepper declarative markup; the input stays a real number field,
// so typing (and no-JS submits) work unchanged. stepDown/stepUp clamp to the
// input's min/max natively. The synthetic change event bubbles so listeners
// keyed on the surrounding form (e.g. the enroll seat projection) see button
// presses exactly like keyboard edits.

document.addEventListener("click", (e) => {
  const button = (e.target as Element | null)?.closest<HTMLElement>(
    "[data-stepper-down], [data-stepper-up]",
  );
  if (!button) return;
  const input = button
    .closest<HTMLElement>("[data-stepper]")
    ?.querySelector<HTMLInputElement>('input[type="number"]');
  if (!input || input.disabled) return;
  if (input.value === "") input.value = input.min || "0";
  else if ("stepperUp" in button.dataset) input.stepUp();
  else input.stepDown();
  input.dispatchEvent(new Event("change", { bubbles: true }));
});
