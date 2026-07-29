// The print page sidebar is not a form — there is nothing to submit or
// apply. Each control in `#print-controls` owns one query param (its `name`):
// changing it rewrites that param and reloads, so untouched params keep their
// defaults and an unticked box or cleared field drops its param entirely.
const controls = document.getElementById("print-controls");

controls?.addEventListener("change", (event) => {
  const control = event.target;
  if (!(control instanceof HTMLInputElement || control instanceof HTMLSelectElement)) return;
  if (!control.name) return;

  const params = new URLSearchParams(globalThis.location.search);
  const value =
    control instanceof HTMLInputElement && control.type === "checkbox"
      ? control.checked
        ? control.value
        : ""
      : control.value;
  if (value) {
    params.set(control.name, value);
  } else {
    params.delete(control.name);
  }
  globalThis.location.search = params.toString();
});
