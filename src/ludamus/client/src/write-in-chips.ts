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
// "Remove") prefixes each chip button's accessible name, and
// data-chips-limit-error (a translated message) shows when a value doesn't
// fit the remaining length budget instead of being dropped silently.

const SEPARATOR = ";";
const JOIN = "; ";

// A page can host more than one chips field, so the limit-error id needs to
// be unique per instance to be a valid aria-describedby target.
let limitErrorSeq = 0;

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
  const limitErrorText = source.dataset.chipsLimitError ?? "";
  const values = splitValues(source.value);
  // The hidden mirror is what maxLength used to cap when this was one plain
  // input. Each chip commit must keep the semicolon-joined mirror under that
  // same budget, or the server (CharField(max_length=...)) rejects the whole
  // submission on a value the UI never warned about.
  const budget = source.maxLength > 0 ? source.maxLength : null;
  const fitsBudget = (candidate: string[]): boolean =>
    budget === null || candidate.join(JOIN).length <= budget;
  // Capacity left for the draft alone, so sync() can bound the *live*, not
  // yet committed, text too — committed chips plus one join separator come
  // out of the same budget before the draft gets what remains.
  const draftBudget = (): number | null => {
    if (budget === null) return null;
    const committedLength = values.length > 0 ? values.join(JOIN).length + JOIN.length : 0;
    return Math.max(0, budget - committedLength);
  };

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

  // Mirrors the server-error `<p class="text-sm text-danger">` pattern
  // dynamic-field.html renders for custom_errors — created lazily so a field
  // that never hits the limit never grows one.
  let limitError: HTMLParagraphElement | null = null;
  const limitErrorId = `write-in-chips-limit-error-${++limitErrorSeq}`;
  const setLimitError = (show: boolean): void => {
    if (show && limitErrorText) {
      if (!limitError) {
        limitError = document.createElement("p");
        limitError.id = limitErrorId;
        limitError.className = "text-sm text-danger mt-1";
        limitError.setAttribute("role", "alert");
        limitError.textContent = limitErrorText;
        shell.after(limitError);
        draft.setAttribute("aria-describedby", limitErrorId);
      }
    } else if (limitError) {
      limitError.remove();
      limitError = null;
      draft.removeAttribute("aria-describedby");
    }
  };

  const sync = (): void => {
    // Bound the *live* draft to what's left of the budget too — not just
    // committed chips — so mid-typing (or a separator paste's leftover
    // remainder, or text a rejected commit put back) can never write a
    // mirror value past what the server accepts. The error tracks the same
    // check, so it shows exactly while the draft is over and clears itself
    // the moment the user shortens it back within budget.
    const remaining = draftBudget();
    const overflowing = remaining !== null && draft.value.length > remaining;
    if (overflowing) draft.value = draft.value.slice(0, remaining ?? 0);
    setLimitError(overflowing);
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

  // Tries to commit one value; the outcome tells callers whether to re-render
  // chips and, for "over-budget", to keep the text visible instead of
  // discarding what the user typed with no explanation (a duplicate is
  // dropped silently — it's already showing as a chip, nothing was lost).
  const tryAddValue = (value: string): "added" | "duplicate" | "over-budget" => {
    if (values.includes(value)) return "duplicate";
    if (!fitsBudget([...values, value])) return "over-budget";
    values.push(value);
    return "added";
  };

  const commitDraft = (): void => {
    const overBudget: string[] = [];
    let added = false;
    for (const value of splitValues(draft.value)) {
      const outcome = tryAddValue(value);
      if (outcome === "added") added = true;
      else if (outcome === "over-budget") overBudget.push(value);
    }
    if (added) renderChips();
    // Over-budget text stays in the draft instead of vanishing; sync() below
    // detects it's still over budget and raises the limit error for it.
    draft.value = overBudget.join(JOIN);
    sync();
  };

  draft.addEventListener("input", () => {
    // Typing (or pasting) the separator commits every completed part and
    // keeps the remainder as the draft.
    if (draft.value.includes(SEPARATOR)) {
      const parts = draft.value.split(SEPARATOR);
      const rest = (parts.pop() ?? "").trimStart();
      const overBudget: string[] = [];
      let added = false;
      for (const value of splitValues(parts.join(SEPARATOR))) {
        const outcome = tryAddValue(value);
        if (outcome === "added") added = true;
        else if (outcome === "over-budget") overBudget.push(value);
      }
      if (added) renderChips();
      // A completed part that didn't fit stays ahead of the in-progress
      // remainder, so a separator paste can't quietly drop it either — sync()
      // below flags it the same way commitDraft's leftovers get flagged.
      draft.value = overBudget.length > 0 ? [...overBudget, rest].join(JOIN) : rest;
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
