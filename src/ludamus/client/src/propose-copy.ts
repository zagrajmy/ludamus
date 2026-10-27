type Value = string[] | boolean | string | null;
type Values = Record<string, Value>;

const snapshots = new WeakMap<HTMLFormElement, Values>();

const controls = (form: HTMLFormElement, name: string): Element[] =>
  [...form.elements].filter(
    (el) => (el as HTMLInputElement).name === name && (el as HTMLInputElement).type !== "file",
  );

const read = (form: HTMLFormElement, names: string[]): Values =>
  Object.fromEntries(
    names.map((name) => {
      const els = controls(form, name);
      const boxes = els.filter(
        (el): el is HTMLInputElement =>
          el instanceof HTMLInputElement && (el.type === "checkbox" || el.type === "radio"),
      );
      if (boxes.length > 1) return [name, boxes.filter((b) => b.checked).map((b) => b.value)];
      if (boxes.length === 1) return [name, boxes[0].checked];
      return [name, (els[0] as HTMLInputElement | undefined)?.value ?? ""];
    }),
  );

const write = (form: HTMLFormElement, values: Values): void => {
  for (const [name, value] of Object.entries(values)) {
    for (const el of controls(form, name)) {
      if (el instanceof HTMLInputElement && (el.type === "checkbox" || el.type === "radio")) {
        el.checked = Array.isArray(value)
          ? value.includes(el.value)
          : value === true || value === el.value;
      } else if (el instanceof HTMLSelectElement) {
        const wanted = typeof value === "string" ? value : "";
        el.value = [...el.options].some((o) => o.value === wanted) ? wanted : "";
      } else if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
        el.value = Array.isArray(value) ? value.join(", ") : typeof value === "string" ? value : "";
      }
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }
};

const markCopied = (panel: HTMLElement, pk: string | null): void => {
  for (const row of panel.querySelectorAll<HTMLElement>("[data-propose-copy-row]")) {
    const on = row.dataset.proposeCopyRow === pk;
    for (const el of row.querySelectorAll<HTMLElement>("[data-propose-copy-from]")) {
      el.hidden = on;
    }
    for (const el of row.querySelectorAll<HTMLElement>(
      "[data-propose-copied], [data-propose-copy-undo]",
    )) {
      el.hidden = !on;
    }
  }
};

document.addEventListener("click", (event) => {
  const button = (event.target as Element | null)?.closest<HTMLButtonElement>(
    "[data-propose-copy-from], [data-propose-copy-undo]",
  );
  const panel = button?.closest<HTMLElement>("[data-propose-copy]");
  const form = panel && document.getElementById(panel.dataset.proposeCopy ?? "");
  if (!button || !panel || !(form instanceof HTMLFormElement)) return;

  const pk = button.dataset.proposeCopyFrom;
  if (pk === undefined) {
    const before = snapshots.get(form);
    if (before) write(form, before);
    snapshots.delete(form);
    markCopied(panel, null);
    panel.querySelector<HTMLElement>(`[data-propose-copy-from]`)?.focus();
    return;
  }

  const all = JSON.parse(
    document.getElementById("propose-copy-values")?.textContent ?? "{}",
  ) as Record<string, Values>;
  const values = all[pk];
  if (!values) return;
  if (!snapshots.has(form)) snapshots.set(form, read(form, Object.keys(values)));
  write(form, values);
  markCopied(panel, pk);
  panel
    .querySelector<HTMLElement>(`[data-propose-copy-row="${pk}"] [data-propose-copy-undo]`)
    ?.focus();
});
