// The "this is now" rule across both compact schedule layouts. The clock is
// the one thing the server cannot render into this page: it is cacheable, and
// a line rendered server-side would be stale the moment it was served.

const HOUR_MS = 3_600_000;

// Shifted, never replaced, by the dev panel below: a demo event's programme
// sits days away from the real clock, so the only way to see the line during
// development is to move now to where the sessions are.
let offsetMs = 0;
const clock = (): number => Date.now() + offsetMs;

const asTime = (at: number): string =>
  new Date(at).toLocaleTimeString([], { hour: "2-digit", hour12: false, minute: "2-digit" });

// The rooms grid: the line belongs to the hour row that contains now, at the
// share of that row the minutes have run through.
const placeInGrid = (at: number): void => {
  const marker = document.querySelector<HTMLElement>("[data-room-lanes-now]");
  if (!marker) return;

  for (const line of document.querySelectorAll<HTMLElement>("[data-hour-start]")) {
    const start = Date.parse(line.dataset.hourStart ?? "");
    if (Number.isNaN(start) || at < start || at >= start + HOUR_MS) continue;
    marker.style.gridRow = line.dataset.laneRow ?? "";
    marker.style.setProperty("--now-frac", String((at - start) / HOUR_MS));
    const time = marker.querySelector<HTMLElement>("[data-room-lanes-now-time]");
    if (time) time.textContent = asTime(at);
    marker.hidden = false;
    return;
  }
  // Outside the programme — between two days, or before or after the event.
  // No hour row owns the moment, so there is nothing to mark.
  marker.hidden = true;
};

// The ledger: a list of rows rather than a time axis, so the line marks the
// seam between what has started and what has not.
const placeInList = (at: number): void => {
  // Scoped to the ledger: the grid's tiles are .session-wrapper as well, and
  // the seam belongs between rows, never inside a tile.
  const rows = document.querySelectorAll<HTMLElement>(".session-grid .session-wrapper");
  if (rows.length === 0) return;
  let marked = false;
  for (const row of rows) {
    // The rendered start, offset and all: data-day/data-hour are the event's
    // local wall clock, which is a different moment in a reader's timezone.
    const start = Date.parse(row.querySelector<HTMLElement>(".session")?.dataset.start ?? "");
    if (!marked && !Number.isNaN(start) && start > at) {
      row.dataset.nowAt = asTime(at);
      marked = true;
    } else {
      delete row.dataset.nowAt;
    }
  }
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

if (import.meta.env.DEV) {
  // Dynamic, so lil-gui and this panel stay out of the production bundle.
  const { mountNowDebug } = await import("./schedule-now-debug");
  mountNowDebug({
    // The first hour the schedule renders, so "jump into the programme" has
    // somewhere to jump to on any seeded event.
    firstHour: () =>
      Date.parse(document.querySelector<HTMLElement>("[data-hour-start]")?.dataset.hourStart ?? ""),
    setOffset: (ms: number) => {
      offsetMs = ms;
      place();
    },
  });
}
