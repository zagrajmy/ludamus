/**
 * Import recipe editor — per row:
 *   - reveal the new-field setup when the target is a "New personal/session
 *     field…" option;
 *   - reveal the options block when the field type takes options;
 *   - reveal the time-slot editor when the target is "Time slots", and let each
 *     option gain/drop window rows.
 *
 * Markup (one per recipe row, keyed by a shared data-row):
 *   <select class="recipe-target" data-row="0">…</select>
 *   <div class="recipe-setup" data-row="0">
 *     <select class="recipe-fieldtype" data-row="0">…</select>
 *     <div class="recipe-options" data-row="0">…</div>
 *   </div>
 *   <div class="recipe-timeslots" data-row="0">
 *     <div class="ts-option"><div class="ts-windows">
 *       <div class="ts-window">…<button class="ts-remove">…</div>
 *     </div><button class="ts-add">…</button></div>
 *   </div>
 */

const NEW_FIELD_TARGETS = new Set(["personal-field", "session-field"]);
const TIME_SLOTS_TARGET = "session.time_slots";

function rowElement(selector: string, row: string): HTMLElement | null {
  return document.querySelector<HTMLElement>(`${selector}[data-row="${row}"]`);
}

function syncTarget(select: HTMLSelectElement): void {
  const row = select.dataset.row ?? "";
  rowElement(".recipe-setup", row)?.classList.toggle(
    "is-open",
    NEW_FIELD_TARGETS.has(select.value),
  );
  rowElement(".recipe-timeslots", row)?.classList.toggle(
    "hidden",
    select.value !== TIME_SLOTS_TARGET,
  );
}

function syncFieldType(select: HTMLSelectElement): void {
  const options = rowElement(".recipe-options", select.dataset.row ?? "");
  options?.classList.toggle("hidden", select.value === "text");
}

function addWindow(button: HTMLElement): void {
  const windows = button.closest(".ts-option")?.querySelector(".ts-windows");
  const last = windows?.querySelector<HTMLElement>(".ts-window:last-child");
  if (!windows || !last) return;
  const clone = last.cloneNode(true) as HTMLElement;
  clone
    .querySelectorAll<HTMLInputElement>("input")
    .forEach((input) => {
      if (input.type !== "hidden") input.value = "";
    });
  windows.appendChild(clone);
}

function removeWindow(button: HTMLElement): void {
  const window_ = button.closest<HTMLElement>(".ts-window");
  const windows = window_?.parentElement;
  if (!window_ || !windows) return;
  if (windows.querySelectorAll(".ts-window").length > 1) {
    window_.remove();
  } else {
    window_
      .querySelectorAll<HTMLInputElement>("input")
      .forEach((input) => {
        if (input.type !== "hidden") input.value = "";
      });
  }
}

document.addEventListener("change", (e) => {
  const select = e.target;
  if (!(select instanceof HTMLSelectElement)) return;
  if (select.classList.contains("recipe-target")) syncTarget(select);
  else if (select.classList.contains("recipe-fieldtype")) syncFieldType(select);
});

document.addEventListener("click", (e) => {
  if (!(e.target instanceof HTMLElement)) return;
  const add = e.target.closest<HTMLElement>(".ts-add");
  if (add) {
    e.preventDefault();
    addWindow(add);
    return;
  }
  const remove = e.target.closest<HTMLElement>(".ts-remove");
  if (remove) {
    e.preventDefault();
    removeWindow(remove);
  }
});

function initRecipe(): void {
  document.querySelectorAll<HTMLSelectElement>(".recipe-target").forEach(syncTarget);
  document
    .querySelectorAll<HTMLSelectElement>(".recipe-fieldtype")
    .forEach(syncFieldType);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initRecipe);
} else {
  initRecipe();
}
