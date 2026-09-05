// The "this is now" rule across both compact schedule layouts, and the dimming
// of what it has passed. The clock is the one thing the server cannot render
// into this page: it is cacheable, and a line rendered server-side would be
// stale the moment it was served.

import { eventTimeZone, programmeDate, programmeDayStartHour } from "./event-time";

const MINUTE_MS = 60_000;

const eventClock = (at: number): string => {
  const timeZone = eventTimeZone();
  if (!timeZone) return "";
  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    hourCycle: "h23",
    minute: "2-digit",
    timeZone,
  }).format(at);
};

const setTime = (marker: HTMLElement, text: string): void => {
  const time = marker.querySelector<HTMLElement>("[data-now-time]");
  if (time) time.textContent = text;
};

// The rooms grid: the line belongs to the row whose band contains now, at the
// share of that band the minutes have run through.
const placeInGrid = (at: number): void => {
  const marker = document.querySelector<HTMLElement>("[data-room-lanes-now]");
  if (!marker) return;

  for (const line of document.querySelectorAll<HTMLElement>("[data-row-start]")) {
    if (line.classList.contains("room-lanes-collapsed")) continue;
    const start = Date.parse(line.dataset.rowStart ?? "");
    const end = Date.parse(line.dataset.rowEnd ?? "");
    if (Number.isNaN(start) || Number.isNaN(end) || at < start || at >= end) continue;
    const overlay = marker.parentElement;
    if (!overlay) return;
    const row = line.getBoundingClientRect();
    const overlayTop = overlay.getBoundingClientRect().top;
    marker.style.top = `${row.top - overlayTop + row.height * ((at - start) / (end - start))}px`;
    setTime(marker, eventClock(at));
    marker.hidden = false;
    return;
  }
  marker.hidden = true;
};

// A row a filter took out is [hidden] (session-filters.ts); a folded day
// hides its rows with CSS instead (schedule-fold.ts) and still counts: the
// programme has begun whether or not yesterday is open on screen.
const shownRows = (): HTMLElement[] =>
  [...document.querySelectorAll<HTMLElement>(".session-grid .session-wrapper")].filter(
    (row) => !row.closest("[hidden]"),
  );

const rowInstant = (row: HTMLElement, field: "end" | "start"): number =>
  Date.parse(row.querySelector<HTMLElement>(".session")?.dataset[field] ?? "");

// The ledger: a list of rows rather than a time axis, so the seam sits between
// what has started and what has not. It belongs to the programme day holding
// now: on a morning before that day's first session it opens the day at its
// top rather than trailing yesterday's last row.
const placeInList = (at: number): void => {
  const seam = document.querySelector<HTMLElement>("[data-schedule-now]");
  if (!seam) return;

  const rows = shownRows();
  const started = rows.filter((row) => rowInstant(row, "start") <= at);
  const lastStarted = started.at(-1);
  const upcoming = rows.some((row) => rowInstant(row, "start") > at);
  const running = started.some((row) => at < rowInstant(row, "end"));
  if (!lastStarted || (!upcoming && !running)) {
    seam.hidden = true;
    return;
  }

  const today = programmeDate(at, eventTimeZone(), programmeDayStartHour());
  const isToday = (row: HTMLElement): boolean =>
    row.closest<HTMLElement>("[data-schedule-day]")?.dataset.day === today;
  const lastStartedToday = started.findLast(isToday);
  const firstToday = rows.find(isToday);
  setTime(seam, eventClock(at));
  if (lastStartedToday) lastStartedToday.after(seam);
  else if (firstToday) firstToday.before(seam);
  else lastStarted.after(seam);
  seam.hidden = false;
};

// What is over reads as over. The served page states which sessions had ended
// when it was rendered, and a schedule left open on a phone at the convention
// outlives that answer by hours — every row it was served bright stays bright.
// Only ever marks: the served state is the floor, so a reader whose device
// clock runs slow cannot light a past programme back up.
const markEnded = (at: number): void => {
  for (const session of document.querySelectorAll<HTMLElement>(
    ".session[data-session-end]:not([data-ended])",
  )) {
    const end = Date.parse(session.dataset.sessionEnd ?? "");
    if (Number.isNaN(end) || end > at) continue;
    session.dataset.ended = "";
    // Every other availability term is about a seat in something still to
    // come, so ending settles the status the filters read (SessionData.
    // availability puts "ended" above all of them).
    session.dataset.status = "ended";
  }
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
  markEnded(at);
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
// A page restored from the back/forward cache resumes with the clock it was
// frozen with: its timer fires late, and until it does the schedule shows an
// hours-old reading of now. The restore is the first chance to correct it.
globalThis.addEventListener("pageshow", start);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) start();
});
document.addEventListener("schedule:filtered", () => queueMicrotask(place));
