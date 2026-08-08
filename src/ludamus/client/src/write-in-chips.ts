// data-write-in-chips: chip entry over a multi-value write-in input (the
// `*_custom` companion of an allow_custom + is_multiple field). The named
// input is the storage contract — the server always receives the
// semicolon-joined string (mills/field_values.py merge_custom) — so this
// module demotes it to a hidden mirror and adds a visible draft input whose
// entries commit to removable chips on Enter or ";". The mirror is re-synced
// on every change (committed chips plus the in-progress draft), so submitting
// mid-typing loses nothing. Without JS the plain text input with its
// "semicolon separated" hint keeps working; no server path changes.
//
// Config rides on the input itself: data-chips-remove-label (a translated
// "Remove") prefixes each chip button's accessible name.

const SEPARATOR = ";";
const JOIN = "; ";

const splitValues = (raw: string): string[] => {
  const values: string[] = [];
  for (const part of raw.split(SEPARATOR)) {
    const value = part.trim();
    if (value && !values.includes(value)) values.push(value);
  }
  return values;
};

const initChipsInput = (source: HTMLInputElement): void => {
  // Idempotent: an input may be re-scanned after an HTMX swap.
  if (source.dataset.chipsReady === "1") return;
  source.dataset.chipsReady = "1";

  const removeLabel = source.dataset.chipsRemoveLabel ?? "Remove";
  const values = splitValues(source.value);
  // The hidden mirror is what maxLength used to cap when this was one plain
  // input. Each chip commit must keep the semicolon-joined mirror under that
  // same budget, or the server (CharField(max_length=...)) rejects the whole
  // submission on a value the UI never warned about.
  const budget = source.maxLength > 0 ? source.maxLength : null;
  const fitsBudget = (candidate: string[]): boolean =>
    budget === null || candidate.join(JOIN).length <= budget;

  // The shell inherits the source's classes so it keeps each form's input
  // look (border, radius, background, spacing) without restating it here.
  const shell = document.createElement("div");
  shell.className = source.className;
  // .write-in-chips (index.css) moves the global focus ring from the inner
  // draft input to the shell, so the control reads as one focused input.
  shell.classList.add(
    "write-in-chips",
    "flex",
    "flex-wrap",
    "items-center",
    "gap-1.5",
    "cursor-text",
  );

  const draft = document.createElement("input");
  draft.type = "text";
  draft.className =
    "flex-1 min-w-32 border-0 bg-transparent p-0 text-sm text-foreground placeholder:text-foreground-muted focus:outline-none";
  const ariaLabel = source.getAttribute("aria-label");
  if (ariaLabel) draft.setAttribute("aria-label", ariaLabel);
  draft.placeholder = source.placeholder;
  if (source.maxLength > 0) draft.maxLength = source.maxLength;

  const sync = (): void => {
    source.value = [...values, draft.value.trim()].filter(Boolean).join(JOIN);
  };

  const renderChips = (): void => {
    for (const chip of shell.querySelectorAll("[data-chip]")) chip.remove();
    for (const value of values) {
      const chip = document.createElement("span");
      chip.dataset.chip = value;
      chip.classList.add("filter-chip", "max-w-full");
      const text = document.createElement("span");
      text.textContent = value;
      text.classList.add("truncate");
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "×";
      remove.setAttribute("aria-label", `${removeLabel}: ${value}`);
      remove.classList.add("focus-visible:outline-2", "focus-visible:outline-primary");
      // Keep focus in the draft on mouse removal, so the blur commit below
      // cannot re-render the chip row out from under this very click.
      remove.addEventListener("pointerdown", (event) => {
        event.preventDefault();
      });
      remove.addEventListener("click", () => {
        const at = values.indexOf(value);
        if (at !== -1) values.splice(at, 1);
        renderChips();
        sync();
        draft.focus();
      });
      chip.append(text, remove);
      draft.before(chip);
    }
  };

  // Commits one value if the resulting joined mirror still fits the budget;
  // returns whether it was added, so callers can tell a full commit from a
  // silently-dropped one.
  const tryAddValue = (value: string): boolean => {
    if (values.includes(value) || !fitsBudget([...values, value])) return false;
    values.push(value);
    return true;
  };

  const commitDraft = (): void => {
    const added = splitValues(draft.value);
    draft.value = "";
    if (added.some((value) => tryAddValue(value))) renderChips();
    sync();
  };

  draft.addEventListener("input", () => {
    // Typing (or pasting) the separator commits every completed part and
    // keeps the remainder as the draft.
    if (draft.value.includes(SEPARATOR)) {
      const parts = draft.value.split(SEPARATOR);
      const rest = (parts.pop() ?? "").trimStart();
      if (splitValues(parts.join(SEPARATOR)).some((value) => tryAddValue(value))) {
        renderChips();
      }
      draft.value = rest;
    }
    sync();
  });

  draft.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && draft.value.trim()) {
      // A non-empty draft becomes a chip; an empty one submits the form.
      event.preventDefault();
      commitDraft();
      return;
    }
    if (event.key === "Backspace" && !draft.value && values.length > 0) {
      values.pop();
      renderChips();
      sync();
    }
  });

  draft.addEventListener("blur", () => {
    if (draft.value.trim()) commitDraft();
  });

  shell.addEventListener("click", (event) => {
    if (event.target === shell) draft.focus();
  });

  source.after(shell);
  shell.append(draft);
  renderChips();
  sync();
  // The draft now carries the accessible name; drop it from the mirror so
  // label lookups (screen readers, tests) resolve to one element.
  source.removeAttribute("aria-label");
  source.removeAttribute("placeholder");
  source.type = "hidden";
};

const initWriteInChips = (root: ParentNode = document): void => {
  for (const input of root.querySelectorAll<HTMLInputElement>("input[data-write-in-chips]")) {
    initChipsInput(input);
  }
};

initWriteInChips();

// This module evaluates once, so inputs swapped in later (the propose wizard
// steps) never run it. Re-scan swapped-in content instead.
document.body.addEventListener("htmx:afterSwap", (event) => {
  const { target } = event as CustomEvent;
  initWriteInChips(target instanceof Element ? target : document);
});
