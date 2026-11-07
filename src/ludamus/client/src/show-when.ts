// Show or hide part of a form by the value of another control in it.
//
//   <div data-show-when="field_type=select">…</div>
//   <option data-hide-when="field_type=checkbox">…</option>
//
// The left side names the controlling control (a select, or a radio group);
// the right side lists the values, space-separated, that the server rendered
// from the form that owns the rule. A hidden part is out of the answer: its
// controls are disabled so they don't submit, and a hidden option that was
// selected hands the selection to the next option still offered.

type Condition = { name: string; showOnMatch: boolean; values: Set<string> };

const parse = (spec: string, showOnMatch: boolean): Condition | undefined => {
  const [name, values = ""] = spec.split("=", 2);
  if (!name) return undefined;
  return { name, showOnMatch, values: new Set(values.split(" ").filter(Boolean)) };
};

const conditionOf = (el: HTMLElement): Condition | undefined => {
  if (el.dataset.showWhen !== undefined) return parse(el.dataset.showWhen, true);
  if (el.dataset.hideWhen !== undefined) return parse(el.dataset.hideWhen, false);
  return undefined;
};

const valueOf = (form: HTMLFormElement, name: string): string => {
  const control = form.elements.namedItem(name);
  if (control instanceof RadioNodeList || control instanceof HTMLSelectElement) {
    return control.value;
  }
  return control instanceof HTMLInputElement ? control.value : "";
};

// Only controls this module disabled are re-enabled, so one the server
// rendered disabled stays that way.
const disabledHere = new WeakSet<Element>();

type Toggleable = HTMLButtonElement | HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;

const setOut = (control: HTMLOptionElement | Toggleable, out: boolean): void => {
  if (out && !control.disabled) {
    control.disabled = true;
    disabledHere.add(control);
  } else if (!out && disabledHere.has(control)) {
    control.disabled = false;
    disabledHere.delete(control);
  }
};

const handOffSelection = (option: HTMLOptionElement): void => {
  if (!option.selected) return;
  let next = option.nextElementSibling;
  while (next instanceof HTMLOptionElement && next.disabled) next = next.nextElementSibling;
  if (next instanceof HTMLOptionElement) next.selected = true;
};

const apply = (el: HTMLElement, shown: boolean): void => {
  el.hidden = !shown;
  if (el instanceof HTMLOptionElement) {
    setOut(el, !shown);
    if (!shown) handOffSelection(el);
    return;
  }
  for (const control of el.querySelectorAll<Toggleable>("button, input, select, textarea")) {
    setOut(control, !shown);
  }
};

const sync = (form: HTMLFormElement): void => {
  for (const el of form.querySelectorAll<HTMLElement>("[data-show-when], [data-hide-when]")) {
    const condition = conditionOf(el);
    if (!condition) continue;
    const matches = condition.values.has(valueOf(form, condition.name));
    apply(el, matches === condition.showOnMatch);
  }
};

const forms = new Set<HTMLFormElement>();
for (const el of document.querySelectorAll<HTMLElement>("[data-show-when], [data-hide-when]")) {
  const form = el.closest("form");
  if (form) forms.add(form);
}
for (const form of forms) {
  form.addEventListener("change", () => sync(form));
  sync(form);
}
