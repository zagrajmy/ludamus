// The category's allowed durations: the h/min steppers add one, a row's
// button removes it. Each row posts its ISO length as `durations`; the server
// normalizes what it receives, so this only has to agree with
// pacts/durations.py on how a length looks, with the units it states in
// #duration-units.

type Units = { hour: string; minute: string };

const readUnits = (): Units => {
  const parsed = JSON.parse(
    document.querySelector("#duration-units")?.textContent ?? "{}",
  ) as Partial<Units>;
  return { hour: parsed.hour ?? "h", minute: parsed.minute ?? "min" };
};

// build_duration's shape, for the steppers' bounded parts.
const toIso = (hours: number, minutes: number): string =>
  hours || minutes ? `PT${hours ? `${hours}H` : ""}${minutes ? `${minutes}M` : ""}` : "";

// format_duration's shape.
const label = (hours: number, minutes: number, units: Units): string =>
  [hours ? `${hours}${units.hour}` : "", minutes ? `${minutes}${units.minute}` : ""]
    .filter(Boolean)
    .join(" ");

const stepperValue = (id: string): number =>
  Number.parseInt(document.querySelector<HTMLInputElement>(`#${id}`)?.value ?? "", 10) || 0;

const list = document.querySelector<HTMLElement>("#durations-list");
const addButton = document.querySelector<HTMLButtonElement>("#add-duration-btn");
const rowTemplate = document.querySelector<HTMLTemplateElement>("#duration-item-template");

if (list && addButton && rowTemplate) {
  const units = readUnits();
  const emptyNote = list.querySelector<HTMLElement>("[data-no-durations]");
  const syncEmptyNote = (): void => {
    if (emptyNote) emptyNote.hidden = list.querySelector("[data-duration-item]") !== null;
  };

  addButton.addEventListener("click", () => {
    const hours = stepperValue("duration-hours");
    const minutes = stepperValue("duration-minutes");
    const iso = toIso(hours, minutes);
    if (!iso) return;
    const taken = [...list.querySelectorAll<HTMLInputElement>('input[name="durations"]')].some(
      (input) => input.value === iso,
    );
    if (taken) return;
    const row = rowTemplate.content.firstElementChild?.cloneNode(true);
    if (!(row instanceof HTMLElement)) return;
    const text = row.querySelector<HTMLElement>("[data-duration-label]");
    const input = row.querySelector<HTMLInputElement>('input[name="durations"]');
    if (text) text.textContent = label(hours, minutes, units);
    if (input) input.value = iso;
    list.append(row);
    syncEmptyNote();
  });

  list.addEventListener("click", (event) => {
    const button = (event.target as Element | null)?.closest("[data-remove-duration]");
    if (!button) return;
    button.closest("[data-duration-item]")?.remove();
    syncEmptyNote();
  });

  syncEmptyNote();
}
