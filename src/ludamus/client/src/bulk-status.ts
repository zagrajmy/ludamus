// Bulk proposal status toolbar: select-all, live count, and disabling the
// action buttons while nothing is selected. The feature degrades without JS —
// the checkboxes and buttons still submit; the server rejects an empty batch.
const form = document.getElementById("bulk-status-form");

if (form instanceof HTMLFormElement) {
  const selectAll = document.getElementById("bulk-select-all");
  const count = document.getElementById("bulk-selected-count");
  const boxes = form.querySelectorAll<HTMLInputElement>(".bulk-row-checkbox");
  const buttons = form.querySelectorAll<HTMLButtonElement>(".bulk-action-btn");

  const update = (): void => {
    const checked = form.querySelectorAll(".bulk-row-checkbox:checked").length;
    if (count) count.textContent = String(checked);
    for (const button of buttons) button.disabled = checked === 0;
    if (selectAll instanceof HTMLInputElement) {
      selectAll.indeterminate = checked > 0 && checked < boxes.length;
      selectAll.checked = boxes.length > 0 && checked === boxes.length;
    }
  };

  for (const box of boxes) box.addEventListener("change", update);

  if (selectAll instanceof HTMLInputElement) {
    selectAll.addEventListener("change", () => {
      for (const box of boxes) box.checked = selectAll.checked;
      update();
    });
  }

  update();
}
