// The "this is now" rule across both compact schedule layouts. The clock is
// the one thing the server cannot render into this page: it is cacheable, and
// a line rendered server-side would be stale the moment it was served.

export const HOUR_MS = 3_600_000;

// Shifted, never replaced, by the dev panel below: a demo event's programme
// sits days away from the real clock, so the only way to see the line during
// development is to move now to where the sessions are.
let offsetMs = 0;
const clock = (): number => Date.now() + offsetMs;

const pad = (part: number): string => String(part).padStart(2, "0");

const eventClock = (instant: string, at: number): string => {
  const zone = /(?:Z|(?<sign>[+-])(?<hours>\d\d):(?<minutes>\d\d))$/.exec(instant);
  const { hours = "0", minutes = "0", sign = "+" } = zone?.groups ?? {};
  const offset = (sign === "-" ? -1 : 1) * (Number(hours) * 60 + Number(minutes));
  const shifted = new Date(at + offset * 60_000);
  return `${pad(shifted.getUTCHours())}:${pad(shifted.getUTCMinutes())}`;
};

const setTime = (marker: HTMLElement, text: string): void => {
  const time = marker.querySelector<HTMLElement>("[data-now-time]");
  if (time) time.textContent = text;
};

// The rooms grid: the line belongs to the hour row that contains now, at the
// share of that row the minutes have run through.
const placeInGrid = (at: number): void => {
  const marker = document.querySelector<HTMLElement>("[data-room-lanes-now]");
  if (!marker) return;

  for (const line of document.querySelectorAll<HTMLElement>("[data-hour-start]")) {
    if (line.classList.contains("room-lanes-collapsed")) continue;
    const instant = line.dataset.hourStart ?? "";
    const start = Date.parse(instant);
    if (Number.isNaN(start) || at < start || at >= start + HOUR_MS) continue;
    marker.style.gridRow = line.dataset.laneRow ?? "";
    marker.style.setProperty("--now-frac", String((at - start) / HOUR_MS));
    setTime(marker, eventClock(instant, at));
    line.after(marker);
    marker.hidden = false;
    return;
  }
  marker.hidden = true;
};

// The ledger: a list of rows rather than a time axis, so the seam moves to sit
// between what has started and what has not.
const placeInList = (at: number): void => {
  const seam = document.querySelector<HTMLElement>("[data-schedule-now]");
  if (!seam) return;

  for (const row of document.querySelectorAll<HTMLElement>(".session-grid .session-wrapper")) {
    if (!row.checkVisibility()) continue;
    // The rendered start, offset and all: the row's day and hour are the
    // event's local wall clock, a different moment in a reader's timezone.
    const instant = row.querySelector<HTMLElement>(".session")?.dataset.start ?? "";
    const start = Date.parse(instant);
    if (Number.isNaN(start) || start <= at) continue;
    setTime(seam, eventClock(instant, at));
    row.before(seam);
    seam.hidden = false;
    return;
  }
  seam.hidden = true;
};

const place = (): void => {
  const at = clock();
  placeInGrid(at);
  placeInList(at);
};

// Once a minute is as fine as the line reads: the pill shows whole minutes and
// an hour row is never short enough for a second to move the line visibly.
let ticking: ReturnType<typeof setInterval> | undefined;
const start = (): void => {
  place();
  ticking ??= setInterval(place, 60_000);
};

start();
document.body.addEventListener("htmx:afterSwap", start);
document.addEventListener("schedule:filtered", place);

if (import.meta.env.DEV) {
  // Dynamic, so lil-gui and this panel stay out of the production bundle.
  const { mountNowDebug } = await import("./schedule-now-debug");
  mountNowDebug((ms: number) => {
    offsetMs = ms;
    place();
  });
}
