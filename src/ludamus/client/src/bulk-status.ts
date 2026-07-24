// Bulk action toolbar (proposals statuses, facilitator triage): select-all,
// live count, and disabling the action buttons while nothing is selected.
// Queries are document-scoped so row checkboxes may live outside the form and
// join it via the `form` attribute (needed where table rows hold their own
// inline forms). Listeners are delegated to the document so they survive HTMX
// swaps of the results region. The feature degrades without JS — the
// checkboxes and buttons still submit; the server rejects an empty batch.
const update = (): void => {
  const form = document.getElementById("bulk-status-form");
  if (!(form instanceof HTMLFormElement)) return;
  const boxes = document.querySelectorAll<HTMLInputElement>(".bulk-row-checkbox");
  const checked = document.querySelectorAll(".bulk-row-checkbox:checked").length;
  const count = document.getElementById("bulk-selected-count");
  if (count) count.textContent = String(checked);
  for (const button of document.querySelectorAll<HTMLButtonElement>(".bulk-action-btn")) {
    button.disabled = checked === 0;
  }
  const selectAll = document.getElementById("bulk-select-all");
  if (selectAll instanceof HTMLInputElement) {
    selectAll.indeterminate = checked > 0 && checked < boxes.length;
    selectAll.checked = boxes.length > 0 && checked === boxes.length;
  }
};

document.addEventListener("change", (event) => {
  const { target } = event;
  if (!(target instanceof HTMLInputElement)) return;
  if (target.id === "bulk-select-all") {
    for (const box of document.querySelectorAll<HTMLInputElement>(".bulk-row-checkbox")) {
      box.checked = target.checked;
    }
    update();
  } else if (target.classList.contains("bulk-row-checkbox")) {
    update();
  }
});

document.body.addEventListener("htmx:afterSwap", update);
update();
