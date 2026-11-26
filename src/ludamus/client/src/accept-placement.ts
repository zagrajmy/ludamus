// The accept page: a space another session holds at any moment between the
// start time picked and the end the session's length gives is marked taken.
// The organizer can still pick it. A room overlap is supported, not advised;
// the booking-conflict UI warns once the session is on the timetable. Every
// time here is the event's wall clock to the minute ("2026-09-05T10:00"), the
// form the start field posts, so times compare as strings and the browser's
// own timezone never enters.

const addMinutes = (wallClock: string, minutes: number): string => {
  // Read as UTC only so that Date does the calendar arithmetic without
  // applying the browser's offset; the result is the same wall clock.
  const at = new Date(`${wallClock}:00Z`);
  at.setUTCMinutes(at.getUTCMinutes() + minutes);
  return at.toISOString().slice(0, 16);
};

for (const form of document.querySelectorAll<HTMLFormElement>("form[data-busy-spaces]")) {
  const space = form.elements.namedItem("space");
  const start = form.elements.namedItem("start_time");
  const data = document.getElementById(form.dataset.busySpaces ?? "");
  if (!(space instanceof HTMLSelectElement) || !(start instanceof HTMLInputElement) || !data) {
    continue;
  }
  const busyBySpace = JSON.parse(data.textContent ?? "{}") as Record<string, [string, string][]>;
  const minutes = Number(form.dataset.durationMinutes ?? "0");
  const takenLabel = form.dataset.takenLabel ?? "";

  const apply = (): void => {
    const from = start.value.slice(0, 16);
    const to = from ? addMinutes(from, minutes) : "";
    for (const option of space.options) {
      if (!option.value) continue;
      // NOTE: on the night the clocks change the wall clock skips or repeats
      // an hour, so the taken label can be an hour off there. The choice
      // still submits; the booking-conflict UI is the warning.
      const isTaken =
        from !== "" &&
        (busyBySpace[option.value] ?? []).some(
          ([busyFrom, busyTo]) => busyFrom < to && busyTo > from,
        );
      const label = option.dataset.label ?? "";
      option.textContent = isTaken ? `${label} · ${takenLabel}` : label;
    }
  };

  start.addEventListener("input", apply);
  apply();
}
