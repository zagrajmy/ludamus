type Value = string[] | boolean | string | null;
type Values = Record<string, Value>;

const snapshots = new WeakMap<HTMLFormElement, Values>();

const asText = (value: Value): string => (typeof value === "string" ? value : "");

// write-in-chips.ts keeps a write-in's answer in a hidden mirror input; any
// other hidden input is the form's own (a one-option choice) and stays.
const isChipsMirror = (el: Element): el is HTMLInputElement =>
  el instanceof HTMLInputElement && el.dataset.writeInMirror !== undefined;

type Control = HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;

const isControl = (el: Element): el is Control =>
  el instanceof HTMLInputElement ||
  el instanceof HTMLSelectElement ||
  el instanceof HTMLTextAreaElement;

const controls = (form: HTMLFormElement, name: string): Control[] =>
  [...form.elements]
    .filter(isControl)
    .filter(
      (el) => el.name === name && el.type !== "file" && (el.type !== "hidden" || isChipsMirror(el)),
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
      return [name, els[0]?.value ?? ""];
    }),
  );

const write = (form: HTMLFormElement, values: Values): void => {
  for (const [name, value] of Object.entries(values)) {
    const els = controls(form, name);
    for (const el of els) {
      if (isChipsMirror(el)) {
        el.dispatchEvent(new CustomEvent("write-in:set", { detail: asText(value) }));
        continue;
      }
      if (el instanceof HTMLInputElement && (el.type === "checkbox" || el.type === "radio")) {
        el.checked = Array.isArray(value)
          ? value.includes(el.value)
          : (value === true && els.length === 1) || value === el.value;
      } else if (el instanceof HTMLSelectElement) {
        const wanted = asText(value);
        el.value = [...el.options].some((o) => o.value === wanted) ? wanted : "";
      } else if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
        el.value = Array.isArray(value) ? value.join(", ") : asText(value);
      }
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }
};

const markCopied = (panel: HTMLElement, copied: boolean): void => {
  for (const el of panel.querySelectorAll<HTMLElement>(
    "[data-propose-copied], [data-propose-copy-undo]",
  )) {
    el.hidden = !copied;
  }
};

document.addEventListener("click", (event) => {
  const button =
    event.target instanceof Element
      ? event.target.closest<HTMLButtonElement>(
          "[data-propose-copy-from], [data-propose-copy-undo]",
        )
      : null;
  const panel = button?.closest<HTMLElement>("[data-propose-copy]");
  const form = panel && document.getElementById(panel.dataset.proposeCopy ?? "");
  if (!button || !panel || !(form instanceof HTMLFormElement)) return;

  const status = panel.querySelector<HTMLElement>("[data-propose-copy-status]");
  const pk = button.dataset.proposeCopyFrom;
  if (pk === undefined) {
    const before = snapshots.get(form);
    if (before) write(form, before);
    snapshots.delete(form);
    markCopied(panel, false);
    if (status) status.textContent = "";
    panel.querySelector<HTMLElement>("[data-menu-button]")?.focus();
    return;
  }

  // SAFETY: the panel's own json_script of reusable_form_values, which the
  // gate builds as a {pk: {field name: value}} map of the form's fields.
  const all = JSON.parse(
    panel.querySelector('script[type="application/json"]')?.textContent ?? "{}",
  ) as Record<string, Values>;
  const values = all[pk];
  if (!values) return;
  if (!snapshots.has(form)) snapshots.set(form, read(form, Object.keys(values)));
  write(form, values);
  markCopied(panel, true);
  if (status)
    status.textContent = panel.querySelector("[data-propose-copied]")?.textContent?.trim() ?? "";
  // Focus leaving the menu closes it (menu.ts).
  panel.querySelector<HTMLElement>("[data-propose-copy-undo]")?.focus();
});
