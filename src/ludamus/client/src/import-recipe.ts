/**
 * Import recipe editor — per row:
 *   - reveal the new-field setup when the target is a "New personal/session
 *     field…" option;
 *   - reveal the options block when the field type takes options;
 *   - auto-fill a name's slug (the .recipe-slug in the same [data-slug-scope])
 *     until that slug is edited — for the field setup and each entity row;
 *   - reveal the time-slot editor when the target is "Time slots", and let each
 *     option gain/drop window rows;
 *   - reveal the track/category entity editor for those targets.
 *
 * Markup (one per recipe row, keyed by a shared data-row):
 *   <select class="recipe-target" data-row="0">…</select>
 *   <div class="recipe-setup" data-row="0">
 *     <div data-slug-scope>
 *       <input class="recipe-name"><input class="recipe-slug">
 *     </div>
 *     <select class="recipe-fieldtype" data-row="0">…</select>
 *     <div class="recipe-options" data-row="0">…</div>
 *   </div>
 *   <div class="recipe-timeslots" data-row="0">
 *     <div class="ts-option"><div class="ts-windows">
 *       <div class="ts-window">…<button class="ts-remove">…</div>
 *     </div><button class="ts-add">…</button></div>
 *   </div>
 *   <div class="recipe-entities" data-row="0">
 *     <div class="ent-option" data-slug-scope>
 *       <input class="recipe-name"><input class="recipe-slug">
 *     </div>…
 *   </div>
 */

const NEW_FIELD_TARGETS = new Set(["personal-field", "session-field"]);
const TIME_SLOTS_TARGET = "session.time_slots";
const ENTITY_TARGETS = new Set(["track", "category"]);

function rowElement(selector: string, row: string): HTMLElement | null {
  return document.querySelector<HTMLElement>(`${selector}[data-row="${row}"]`);
}

// ASCII slug mirroring the server's slugify, for the live name→slug preview.
function slugify(value: string): string {
  return value
    .normalize("NFKD")
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .trim()
    .replace(/[\s-]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

// The slug paired with a name lives in the same [data-slug-scope] (the field
// setup, or one track/category row).
function pairedSlug(name: HTMLElement): HTMLInputElement | null {
  const slug = name.closest("[data-slug-scope]")?.querySelector(".recipe-slug");
  return slug instanceof HTMLInputElement ? slug : null;
}

function syncSlug(name: HTMLInputElement): void {
  const slug = pairedSlug(name);
  if (slug && !slug.dataset.edited) slug.value = slugify(name.value);
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
  rowElement(".recipe-entities", row)?.classList.toggle(
    "hidden",
    !ENTITY_TARGETS.has(select.value),
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

document.addEventListener("input", (e) => {
  const input = e.target;
  if (!(input instanceof HTMLInputElement)) return;
  if (input.classList.contains("recipe-name")) syncSlug(input);
  else if (input.classList.contains("recipe-slug"))
    input.dataset.edited = input.value ? "true" : "";
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
  // Preserve a hand-customised slug (one that differs from its name's slug); a
  // blank or name-matching slug stays auto-synced as the operator types.
  document.querySelectorAll<HTMLInputElement>(".recipe-name").forEach((name) => {
    const slug = pairedSlug(name);
    if (slug && slug.value && slug.value !== slugify(name.value)) {
      slug.dataset.edited = "true";
    }
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initRecipe);
} else {
  initRecipe();
}
