// The accept page, when both its space and its time are left to choose: a
// space another session holds during the picked time is shown taken and
// cannot be picked. Options the server already marked taken (taken at every
// time) stay so. With either field settled the server marks everything and
// this script has nothing to do.
for (const form of document.querySelectorAll<HTMLFormElement>("form[data-taken-spaces]")) {
  const space = form.elements.namedItem("space");
  const slot = form.elements.namedItem("time_slot");
  const data = document.getElementById(form.dataset.takenSpaces ?? "");
  if (!(space instanceof HTMLSelectElement) || !(slot instanceof HTMLSelectElement) || !data) {
    continue;
  }
  const takenBySlot = JSON.parse(data.textContent ?? "{}") as Record<string, number[]>;
  const takenLabel = form.dataset.takenLabel ?? "";
  const alwaysTaken = new Set(
    [...space.options].filter((option) => option.disabled).map((option) => option.value),
  );

  const apply = (): void => {
    const taken = new Set((takenBySlot[slot.value] ?? []).map(String));
    for (const option of space.options) {
      if (!option.value || alwaysTaken.has(option.value)) continue;
      const isTaken = taken.has(option.value);
      option.disabled = isTaken;
      const label = option.dataset.label ?? "";
      option.textContent = isTaken ? `${label} · ${takenLabel}` : label;
    }
    if (space.selectedOptions[0]?.disabled) space.value = "";
  };

  slot.addEventListener("change", apply);
  apply();
}
