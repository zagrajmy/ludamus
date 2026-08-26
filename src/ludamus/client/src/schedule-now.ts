// The "this is now" rule across both compact schedule layouts. The clock is
// the one thing the server cannot render into this page: it is cacheable, and
// a line rendered server-side would be stale the moment it was served.

const HOUR_MS = 3_600_000;
const MINUTE_MS = 60_000;

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
    const overlay = marker.parentElement;
    if (!overlay) return;
    const row = line.getBoundingClientRect();
    const overlayTop = overlay.getBoundingClientRect().top;
    marker.style.top = `${row.top - overlayTop + row.height * ((at - start) / HOUR_MS)}px`;
    setTime(marker, eventClock(instant, at));
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

  let lastStarted: { instant: string; row: HTMLElement } | undefined;
  let programmeIsRunning = false;
  for (const row of document.querySelectorAll<HTMLElement>(".session-grid .session-wrapper")) {
    if (!row.checkVisibility()) continue;
    const session = row.querySelector<HTMLElement>(".session");
    const instant = session?.dataset.start ?? "";
    const start = Date.parse(instant);
    if (Number.isNaN(start)) continue;
    if (start > at) {
      setTime(seam, eventClock(instant, at));
      row.before(seam);
      seam.hidden = false;
      return;
    }

    lastStarted = { instant, row };
    const end = Date.parse(session?.dataset.end ?? "");
    programmeIsRunning ||= !Number.isNaN(end) && at < end;
  }

  if (lastStarted && programmeIsRunning) {
    setTime(seam, eventClock(lastStarted.instant, at));
    lastStarted.row.after(seam);
    seam.hidden = false;
    return;
  }
  seam.hidden = true;
};

let observedGrid: HTMLElement | null = null;
let layoutObserver: ResizeObserver | null = null;

const observeGridLayout = (): void => {
  const grid = document.querySelector<HTMLElement>(".room-lanes-body");
  if (grid === observedGrid) return;
  layoutObserver?.disconnect();
  observedGrid = grid;
  if (grid) layoutObserver?.observe(grid);
};

const place = (): void => {
  observeGridLayout();
  const at = Math.floor(Date.now() / MINUTE_MS) * MINUTE_MS;
  placeInGrid(at);
  placeInList(at);
};

layoutObserver = new ResizeObserver(place);

let ticking: ReturnType<typeof setTimeout> | undefined;
const queueNextMinute = (): void => {
  if (ticking) clearTimeout(ticking);
  ticking = setTimeout(
    () => {
      place();
      queueNextMinute();
    },
    MINUTE_MS - (Date.now() % MINUTE_MS),
  );
};

const start = (): void => {
  place();
  queueNextMinute();
};

start();
document.body.addEventListener("htmx:afterSwap", start);
document.addEventListener("schedule:filtered", place);
