/**
 * Import recipe editor — per row:
 *   - reveal the new-field setup when the target is a "New personal/session
 *     field…" option;
 *   - reveal the options block when the field type takes options;
 *   - auto-fill a name's slug (the [data-recipe-slug] in the same [data-slug-scope])
 *     until the operator types into the slug directly, OR the row is confirmed
 *     (slug stays locked); emptying the slug field unlocks auto-sync again.
 *     Applies to field setup + each entity row;
 *   - reveal the available-days editor when the target is "Available days", and
 *     let each option gain/drop day rows;
 *   - reveal the track/category entity editor for those targets.
 *
 * Markup (one per recipe row, keyed by a shared data-row):
 *   <select data-recipe-target data-row="0">…</select>
 *   <div class="recipe-setup" data-row="0">
 *     <div data-slug-scope>
 *       <input data-recipe-name><input data-recipe-slug>
 *     </div>
 *     <select data-recipe-fieldtype data-row="0">…</select>
 *     <div data-recipe-options data-row="0">…</div>
 *   </div>
 *   <div data-recipe-days data-row="0">
 *     <div data-day-option><div data-day-rows>
 *       <div data-day-row>…<button data-day-remove>…</div>
 *     </div><button data-day-add>…</button></div>
 *   </div>
 *   <div data-recipe-entities data-row="0">
 *     <div data-slug-scope>
 *       <input data-recipe-name><input data-recipe-slug>
 *     </div>…
 *   </div>
 */

import slugifyLib from "slugify";

const NEW_FIELD_TARGETS = new Set(["personal-field", "session-field"]);
const AVAILABLE_DAYS_TARGET = "session.available_days";
const DURATION_TARGET = "session.duration";
const ENTITY_TARGETS = new Set(["category", "track"]);

function rowElement(selector: string, row: string): HTMLElement | null {
  return document.querySelector<HTMLElement>(`${selector}[data-row="${row}"]`);
}

// Lowercase ASCII slug for the live name→slug preview. Mirrors the server-side
// slugify, which applies the same simov/slugify transliteration table via a
// hand-maintained Python copy (mills/submissions.py: _TRANSLITERATION).
function slugify(value: string): string {
  return slugifyLib(value, { locale: "pl", lower: true, strict: true });
}

// The slug paired with a name lives in the same [data-slug-scope] (the field
// setup, or one track/category row).
function pairedSlug(name: HTMLElement): HTMLInputElement | null {
  const slug = name.closest("[data-slug-scope]")?.querySelector("[data-recipe-slug]");
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
  rowElement("[data-recipe-days]", row)?.classList.toggle(
    "hidden",
    select.value !== AVAILABLE_DAYS_TARGET,
  );
  rowElement("[data-recipe-entities]", row)?.classList.toggle(
    "hidden",
    !ENTITY_TARGETS.has(select.value),
  );
  rowElement("[data-recipe-durations]", row)?.classList.toggle(
    "hidden",
    select.value !== DURATION_TARGET,
  );
  rowElement("[data-recipe-overrides]", row)?.classList.toggle("hidden", select.value === "ignore");
}

function syncFieldType(select: HTMLSelectElement): void {
  const options = rowElement("[data-recipe-options]", select.dataset.row ?? "");
  options?.classList.toggle("hidden", select.value === "text");
}

function addDay(button: HTMLElement): void {
  const days = button.closest("[data-day-option]")?.querySelector("[data-day-rows]");
  const last = days?.querySelector<HTMLElement>("[data-day-row]:last-child");
  if (!days || !last) return;
  const clone = last.cloneNode(true) as HTMLElement;
  for (const input of clone.querySelectorAll<HTMLInputElement>("input")) {
    if (input.type !== "hidden") input.value = "";
  }
  days.append(clone);
}

function removeDay(button: HTMLElement): void {
  const day = button.closest<HTMLElement>("[data-day-row]");
  const days = day?.parentElement;
  if (!day || !days) return;
  if (days.querySelectorAll("[data-day-row]").length > 1) {
    day.remove();
  } else {
    for (const input of day.querySelectorAll<HTMLInputElement>("input")) {
      if (input.type !== "hidden") input.value = "";
    }
  }
}

function addOverride(button: HTMLElement): void {
  const rows = button
    .closest<HTMLElement>("[data-recipe-overrides]")
    ?.querySelector<HTMLElement>("[data-ov-rows]");
  const last = rows?.querySelector<HTMLElement>("[data-ov-row]:last-child");
  if (!rows || !last) return;
  const clone = last.cloneNode(true) as HTMLElement;
  for (const input of clone.querySelectorAll<HTMLInputElement>("input")) {
    input.value = "";
  }
  rows.append(clone);
}

function removeOverride(button: HTMLElement): void {
  const row = button.closest<HTMLElement>("[data-ov-row]");
  const rows = row?.parentElement;
  if (!row || !rows) return;
  if (rows.querySelectorAll("[data-ov-row]").length > 1) {
    row.remove();
  } else {
    for (const input of row.querySelectorAll<HTMLInputElement>("input")) {
      input.value = "";
    }
  }
}

document.addEventListener("change", (e) => {
  const select = e.target;
  if (!(select instanceof HTMLSelectElement)) return;
  if ("recipeTarget" in select.dataset) syncTarget(select);
  else if ("recipeFieldtype" in select.dataset) syncFieldType(select);
});

document.addEventListener("input", (e) => {
  const input = e.target;
  if (!(input instanceof HTMLInputElement)) return;
  if ("recipeName" in input.dataset) syncSlug(input);
  else if ("recipeSlug" in input.dataset) input.dataset.edited = input.value ? "true" : "";
});

document.addEventListener("click", (e) => {
  if (!(e.target instanceof HTMLElement)) return;
  const dayAdd = e.target.closest<HTMLElement>("[data-day-add]");
  if (dayAdd) {
    e.preventDefault();
    addDay(dayAdd);
    return;
  }
  const dayRemove = e.target.closest<HTMLElement>("[data-day-remove]");
  if (dayRemove) {
    e.preventDefault();
    removeDay(dayRemove);
    return;
  }
  const ovAdd = e.target.closest<HTMLElement>("[data-ov-add]");
  if (ovAdd) {
    e.preventDefault();
    addOverride(ovAdd);
    return;
  }
  const ovRemove = e.target.closest<HTMLElement>("[data-ov-remove]");
  if (ovRemove) {
    e.preventDefault();
    removeOverride(ovRemove);
  }
});

function initRecipe(): void {
  for (const target of document.querySelectorAll<HTMLSelectElement>("[data-recipe-target]")) {
    syncTarget(target);
  }
  for (const fieldType of document.querySelectorAll<HTMLSelectElement>("[data-recipe-fieldtype]")) {
    syncFieldType(fieldType);
  }
  // Lock every populated slug in a confirmed row from name-driven auto-sync.
  // The input listener clears the flag when the operator empties the slug,
  // reopening auto-sync for that field.
  for (const row of document.querySelectorAll<HTMLElement>(
    "[data-recipe-row][data-confirmed='true']",
  )) {
    for (const slug of row.querySelectorAll<HTMLInputElement>("[data-recipe-slug]")) {
      if (slug.value) slug.dataset.edited = "true";
    }
  }
}

// Column-key chip editor (Run tab): selected columns as removable chips with
// hidden inputs, plus a dropdown of the remaining candidates. Click "Add" to
// move the dropdown's selected value into the chip list; click a chip's × to
// drop it back into the dropdown. Submission is plain form POST — the hidden
// inputs carry the selection under the field name in data-name, so one editor
// drives both the unique-key and facilitator-key pickers.
function initColumnKeys(root: HTMLElement): void {
  const list = root.querySelector<HTMLElement>("[data-column-keys-list]");
  const select = root.querySelector<HTMLSelectElement>("[data-column-keys-select]");
  const addBtn = root.querySelector<HTMLButtonElement>("[data-column-keys-add]");
  const { name } = root.dataset;
  if (!list || !select || !addBtn || !name) return;

  const removeEmpty = (): void => {
    list.querySelector("[data-column-keys-empty]")?.remove();
  };

  const restoreEmptyIfNeeded = (): void => {
    if (list.querySelector("li:not([data-column-keys-empty])")) return;
    const empty = document.createElement("li");
    empty.dataset.columnKeysEmpty = "";
    empty.className = "text-xs text-foreground-muted";
    empty.textContent = root.dataset.emptyLabel ?? "";
    list.append(empty);
  };

  const addToDropdown = (value: string): void => {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = value;
    select.append(opt);
  };

  const removeChip = (li: HTMLElement, value: string): void => {
    li.remove();
    addToDropdown(value);
    restoreEmptyIfNeeded();
  };

  const buildChip = (value: string): HTMLLIElement => {
    const li = document.createElement("li");
    li.className =
      "inline-flex max-w-full items-center gap-1 rounded-full border border-border bg-bg-secondary px-3 py-1 text-sm text-foreground-secondary";

    const hidden = document.createElement("input");
    hidden.type = "hidden";
    hidden.name = name;
    hidden.value = value;
    li.append(hidden);

    const label = document.createElement("span");
    label.className = "truncate";
    label.textContent = value;
    label.title = value;
    li.append(label);

    const btn = document.createElement("button");
    btn.type = "button";
    btn.dataset.columnKeysRemove = "";
    btn.className =
      "ml-1 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-foreground-muted hover:bg-bg-tertiary hover:text-foreground";
    // Same msgid as the server-rendered chips: the template hands over the
    // translated sentence with a placeholder standing in for the column name.
    btn.setAttribute(
      "aria-label",
      (root.dataset.removeLabel ?? "Remove __COL__").replace("__COL__", value),
    );
    btn.textContent = "×";
    btn.addEventListener("click", () => removeChip(li, value));
    li.append(btn);

    return li;
  };

  for (const btn of list.querySelectorAll<HTMLButtonElement>("[data-column-keys-remove]")) {
    btn.addEventListener("click", () => {
      const li = btn.closest<HTMLLIElement>("li");
      const value = li?.querySelector<HTMLInputElement>(`input[name='${name}']`)?.value;
      if (li && value) removeChip(li, value);
    });
  }

  addBtn.addEventListener("click", () => {
    const { value } = select;
    if (!value) return;
    removeEmpty();
    list.append(buildChip(value));
    select.querySelector(`option[value="${CSS.escape(value)}"]`)?.remove();
    select.value = "";
  });
}

function initColumnKeysAll(): void {
  for (const element of document.querySelectorAll<HTMLElement>("[data-column-keys]")) {
    initColumnKeys(element);
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    initRecipe();
    initColumnKeysAll();
  });
} else {
  initRecipe();
  initColumnKeysAll();
}

// The review region is HTMX-swapped when walking Prev/Next/dropdown through
// questions; re-seed visibility classes and slug-edited flags on the freshly
// inserted DOM.
document.body.addEventListener("htmx:afterSwap", (event) => {
  const target = (event as CustomEvent).detail?.target;
  if (target instanceof HTMLElement && target.id === "import-review-region") {
    initRecipe();
  }
});
