/**
 * Import recipe editor — per row:
 *   - reveal the new-field setup when the target is a "New personal/session
 *     field…" option;
 *   - reveal the options block when the field type takes options;
 *   - auto-fill a name's slug (the .recipe-slug in the same [data-slug-scope])
 *     until the operator types into the slug directly, OR the row is confirmed
 *     (slug stays locked); emptying the slug field unlocks auto-sync again.
 *     Applies to field setup + each entity row;
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

import slugifyLib from "slugify";

const NEW_FIELD_TARGETS = new Set(["personal-field", "session-field"]);
const TIME_SLOTS_TARGET = "session.time_slots";
const DURATION_TARGET = "session.duration";
const ENTITY_TARGETS = new Set(["track", "category"]);

function rowElement(selector: string, row: string): HTMLElement | null {
  return document.querySelector<HTMLElement>(`${selector}[data-row="${row}"]`);
}

// Lowercase ASCII slug for the live name→slug preview. Mirrors the server-side
// slugify, which applies the same simov/slugify transliteration table via a
// hand-maintained Python copy (mills/submissions.py: _TRANSLITERATION).
function slugify(value: string): string {
  return slugifyLib(value, { lower: true, strict: true, locale: "pl" });
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
  rowElement(".recipe-durations", row)?.classList.toggle(
    "hidden",
    select.value !== DURATION_TARGET,
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
  // Lock every populated slug in a confirmed row from name-driven auto-sync.
  // The input listener clears the flag when the operator empties the slug,
  // reopening auto-sync for that field.
  document
    .querySelectorAll<HTMLElement>("[data-recipe-row][data-confirmed='true']")
    .forEach((row) => {
      row.querySelectorAll<HTMLInputElement>(".recipe-slug").forEach((slug) => {
        if (slug.value) slug.dataset.edited = "true";
      });
    });
}

// Unique-key columns chip editor (Run tab): selected columns as removable
// chips with hidden inputs, plus a dropdown of the remaining candidates.
// Click "Add" to move the dropdown's selected value into the chip list;
// click a chip's × to drop it back into the dropdown. Submission is plain
// form POST — the hidden inputs name="unique_key_columns" carry the
// selection.
function initUniqueKeys(root: HTMLElement): void {
  const list = root.querySelector<HTMLElement>("[data-unique-keys-list]");
  const select = root.querySelector<HTMLSelectElement>("[data-unique-keys-select]");
  const addBtn = root.querySelector<HTMLButtonElement>("[data-unique-keys-add]");
  if (!list || !select || !addBtn) return;

  const removeEmpty = (): void => {
    list.querySelector("[data-unique-keys-empty]")?.remove();
  };

  const restoreEmptyIfNeeded = (): void => {
    if (list.querySelector("li:not([data-unique-keys-empty])")) return;
    const empty = document.createElement("li");
    empty.dataset.uniqueKeysEmpty = "";
    empty.className = "text-xs text-foreground-muted";
    empty.textContent = root.dataset.emptyLabel ?? "";
    list.appendChild(empty);
  };

  const addToDropdown = (value: string): void => {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = value;
    select.appendChild(opt);
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
    hidden.name = "unique_key_columns";
    hidden.value = value;
    li.appendChild(hidden);

    const label = document.createElement("span");
    label.className = "truncate";
    label.textContent = value;
    label.title = value;
    li.appendChild(label);

    const btn = document.createElement("button");
    btn.type = "button";
    btn.dataset.uniqueKeysRemove = "";
    btn.className =
      "ml-1 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-foreground-muted hover:bg-bg-tertiary hover:text-foreground";
    btn.setAttribute("aria-label", `Remove ${value}`);
    btn.textContent = "×";
    btn.addEventListener("click", () => removeChip(li, value));
    li.appendChild(btn);

    return li;
  };

  list
    .querySelectorAll<HTMLButtonElement>("[data-unique-keys-remove]")
    .forEach((btn) => {
      btn.addEventListener("click", () => {
        const li = btn.closest<HTMLLIElement>("li");
        const value = li?.querySelector<HTMLInputElement>(
          "input[name='unique_key_columns']",
        )?.value;
        if (li && value) removeChip(li, value);
      });
    });

  addBtn.addEventListener("click", () => {
    const value = select.value;
    if (!value) return;
    removeEmpty();
    list.appendChild(buildChip(value));
    select.querySelector(`option[value="${CSS.escape(value)}"]`)?.remove();
    select.value = "";
  });
}

function initUniqueKeysAll(): void {
  document
    .querySelectorAll<HTMLElement>("[data-unique-keys]")
    .forEach(initUniqueKeys);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    initRecipe();
    initUniqueKeysAll();
  });
} else {
  initRecipe();
  initUniqueKeysAll();
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
