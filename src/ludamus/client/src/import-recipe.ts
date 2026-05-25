/**
 * Import recipe editor — per row:
 *   - reveal the new-field setup when the target is a "New personal/session
 *     field…" option;
 *   - reveal the options block when the field type takes options.
 *
 * Markup (one per recipe row, keyed by a shared data-row):
 *   <select class="recipe-target" data-row="0">…</select>
 *   <div class="recipe-setup" data-row="0">
 *     <select class="recipe-fieldtype" data-row="0">…</select>
 *     <div class="recipe-options" data-row="0">…</div>
 *   </div>
 */

const NEW_FIELD_TARGETS = new Set(["personal-field", "session-field"]);

function rowElement(selector: string, row: string): HTMLElement | null {
  return document.querySelector<HTMLElement>(`${selector}[data-row="${row}"]`);
}

function syncTarget(select: HTMLSelectElement): void {
  const setup = rowElement(".recipe-setup", select.dataset.row ?? "");
  setup?.classList.toggle("is-open", NEW_FIELD_TARGETS.has(select.value));
}

function syncFieldType(select: HTMLSelectElement): void {
  const options = rowElement(".recipe-options", select.dataset.row ?? "");
  options?.classList.toggle("hidden", select.value === "text");
}

document.addEventListener("change", (e) => {
  const select = e.target;
  if (!(select instanceof HTMLSelectElement)) return;
  if (select.classList.contains("recipe-target")) syncTarget(select);
  else if (select.classList.contains("recipe-fieldtype")) syncFieldType(select);
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
