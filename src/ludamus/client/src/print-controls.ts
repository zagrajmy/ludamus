// The print page sidebar is not a form — there is nothing to submit or
// apply. Each control in `#print-controls` owns one query param (its `name`):
// changing it rewrites that param and reloads, so untouched params keep their
// defaults and an unticked box or cleared field drops its param entirely.
const controls = document.getElementById("print-controls");

type Control = HTMLInputElement | HTMLSelectElement;

const controlValue = (control: Control): string =>
  control instanceof HTMLInputElement && control.type === "checkbox"
    ? control.checked
      ? control.value
      : ""
    : control.value;

const apply = (control: Control): void => {
  const params = new URLSearchParams(globalThis.location.search);
  const value = controlValue(control);
  if (value) {
    params.set(control.name, value);
  } else {
    params.delete(control.name);
  }
  globalThis.location.search = params.toString();
};

// Was the control edited relative to the server-rendered state? True only
// when a change fired before this module loaded (see the healing pass below).
const editedBeforeLoad = (control: Control): boolean =>
  control instanceof HTMLSelectElement
    ? [...control.options].some((option) => option.selected !== option.defaultSelected)
    : control.type === "checkbox"
      ? control.checked !== control.defaultChecked
      : control.value !== control.defaultValue;

controls?.addEventListener("change", (event) => {
  const control = event.target;
  if (!(control instanceof HTMLInputElement || control instanceof HTMLSelectElement)) return;
  if (!control.name) return;
  apply(control);
});

// Heal the startup race: a control changed before this module executed fired
// its change event into the void. Apply the first such edit now (applying one
// navigates, which re-renders everything anyway).
for (const control of controls?.querySelectorAll<Control>("select[name], input[name]") ?? []) {
  if (editedBeforeLoad(control)) {
    apply(control);
    break;
  }
}
