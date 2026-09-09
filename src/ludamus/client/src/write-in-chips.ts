const JOIN = "; ";

const splitValues = (raw: string): string[] => [
  ...new Set(
    raw
      .split(";")
      .map((part) => part.trim())
      .filter(Boolean),
  ),
];

const initChipsInput = (draft: HTMLInputElement): void => {
  if (draft.dataset.chipsReady) return;
  draft.dataset.chipsReady = "1";

  const removeLabel = draft.dataset.chipsRemoveLabel ?? "";
  const limitErrorText = draft.dataset.chipsLimitError ?? "";
  const { maxLength } = draft;
  const describedBy = draft.getAttribute("aria-describedby");
  const invalid = draft.getAttribute("aria-invalid");
  const initialValues = splitValues(draft.value);
  const chips = new Map<string, HTMLSpanElement>();

  const mirror = document.createElement("input");
  mirror.type = "hidden";
  mirror.name = draft.name;
  mirror.disabled = draft.disabled;
  draft.removeAttribute("name");
  // SAFETY: validate the complete serialized answer without truncating pasted text.
  draft.removeAttribute("maxlength");

  const shell = document.createElement("div");
  shell.className = draft.className;
  shell.classList.add(
    "write-in-chips",
    "flex",
    "flex-wrap",
    "items-center",
    "gap-1.5",
    "cursor-text",
  );
  draft.before(mirror, shell);
  shell.append(draft);
  draft.className =
    "flex-1 min-w-48 max-w-full w-48 border-0 bg-transparent p-0 text-base sm:text-sm text-foreground placeholder:text-foreground-muted focus:outline-none";

  const error = document.createElement("p");
  error.id = `${draft.id}-chips-limit`;
  error.className = "text-sm text-danger mt-1";
  error.setAttribute("role", "alert");
  error.hidden = true;
  shell.after(error);

  const hint = shell.parentElement?.querySelector<HTMLElement>("[data-chips-hint]");
  if (hint) hint.textContent = hint.dataset.chipsHint ?? "";

  const sync = (): boolean => {
    mirror.value = [...new Set([...chips.keys(), ...splitValues(draft.value)])].join(JOIN);
    const overflowing = maxLength >= 0 && mirror.value.length > maxLength;
    draft.setCustomValidity(overflowing ? limitErrorText : "");
    error.hidden = !overflowing;
    error.textContent = overflowing ? limitErrorText : "";
    const description = [describedBy, overflowing ? error.id : ""].filter(Boolean).join(" ");
    if (description) draft.setAttribute("aria-describedby", description);
    else draft.removeAttribute("aria-describedby");
    if (overflowing || invalid)
      draft.setAttribute("aria-invalid", overflowing ? "true" : (invalid ?? "false"));
    else draft.removeAttribute("aria-invalid");
    return !overflowing;
  };

  const removeChip = (value: string): void => {
    chips.get(value)?.remove();
    chips.delete(value);
    sync();
  };

  const addChip = (value: string): void => {
    if (chips.has(value)) return;
    const chip = document.createElement("span");
    chip.className =
      "inline-flex items-center gap-1 rounded-2xl font-medium max-w-full bg-warm-200/80 dark:bg-neutral-700 text-warm-700 dark:text-neutral-300 text-sm px-2.5 py-0.5";
    const text = document.createElement("span");
    text.textContent = value;
    text.className = "truncate";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    remove.disabled = draft.disabled || draft.readOnly;
    remove.setAttribute("aria-label", `${removeLabel}: ${value}`);
    remove.className =
      "inline-flex items-center justify-center size-4 shrink-0 rounded-full cursor-pointer text-xs leading-none hover:bg-warm-300 dark:hover:bg-neutral-600 focus-visible:outline-2 focus-visible:outline-primary";
    remove.addEventListener("click", () => {
      removeChip(value);
      draft.focus();
    });
    chip.append(text, remove);
    chips.set(value, chip);
    draft.before(chip);
  };

  const commit = (completed: string, remainder = ""): void => {
    if (!sync()) return;
    for (const value of splitValues(completed)) addChip(value);
    draft.value = remainder;
    sync();
  };

  const acceptSeparators = (): void => {
    const separator = draft.value.lastIndexOf(";");
    commit(draft.value.slice(0, separator), draft.value.slice(separator + 1).trimStart());
  };

  draft.addEventListener("input", (event) => {
    if (event instanceof InputEvent && event.isComposing) return;
    if (draft.value.includes(";")) acceptSeparators();
    else sync();
  });
  draft.addEventListener("compositionend", () => {
    if (draft.value.includes(";")) acceptSeparators();
    else sync();
  });
  draft.addEventListener("keydown", (event) => {
    if (event.isComposing || draft.readOnly) return;
    if (event.key === "Enter" && draft.value.trim()) {
      event.preventDefault();
      commit(draft.value);
    } else if (event.key === "Backspace" && !draft.value) {
      const last = [...chips.keys()].at(-1);
      if (last !== undefined) removeChip(last);
    }
  });
  draft.addEventListener("blur", () => {
    if (draft.value.trim()) commit(draft.value);
  });
  shell.addEventListener("click", (event) => {
    if (event.target === shell) draft.focus();
  });

  draft.value = "";
  for (const value of initialValues) addChip(value);
  sync();
};

const initWriteInChips = (): void => {
  for (const input of document.querySelectorAll<HTMLInputElement>("input[data-write-in-chips]")) {
    initChipsInput(input);
  }
};

initWriteInChips();
document.body.addEventListener("htmx:afterSwap", initWriteInChips);
