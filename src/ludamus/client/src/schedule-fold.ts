// Folding days across the schedule layouts. A day heading doubles as a
// disclosure button ([data-day-fold]): the ledger and the card grid fold their
// [data-schedule-day] section (CSS hides its slots), the rooms grid marks its
// [data-day-heading] folded and room-lanes.ts collapses the day's tracks. Days
// whose local date is already behind the event's today arrive folded —
// yesterday's programme is one click away, not in the way. Fold state is a
// reading gesture: nothing of it reaches the URL or the filters.

const announce = (): void => {
  document.dispatchEvent(new CustomEvent("schedule:filtered"));
};

// The event's calendar date decides what counts as "already over": visiting on
// Saturday folds Friday, whatever the visitor's own timezone says.
const eventToday = (): string => {
  const timeZone =
    document.querySelector<HTMLElement>("[data-event-time-zone]")?.dataset.eventTimeZone;
  return new Intl.DateTimeFormat("en-CA", timeZone ? { timeZone } : {}).format(new Date());
};

const isFolded = (holder: HTMLElement): boolean => "folded" in holder.dataset;

// The fold state lives on the holder as data-folded (the CSS hook), with the
// button's aria-expanded kept in step. The rooms grid keeps one holder per day
// — its [data-day-heading] — and room-lanes.ts mirrors it onto the seam clones
// and the sticky day bar.
const setFolded = (holder: HTMLElement, folded: boolean): void => {
  if (folded) holder.dataset.folded = "";
  else delete holder.dataset.folded;
  holder.querySelector("[data-day-fold]")?.setAttribute("aria-expanded", String(!folded));
};

const laneHeading = (lanes: HTMLElement, day: string): HTMLElement | null =>
  lanes.querySelector<HTMLElement>(`[data-lane-day-heading="${CSS.escape(day)}"]`);

const toggleFrom = (toggle: HTMLElement): void => {
  // A seam button sits inside the day's heading; the sticky bar stands outside
  // the grid and names the day it currently shows via data-fold-day.
  const lanes = toggle.closest<HTMLElement>(".room-lanes");
  const holder =
    toggle.closest<HTMLElement>("[data-schedule-day]") ??
    toggle.closest<HTMLElement>("[data-day-heading]") ??
    (lanes && toggle.dataset.foldDay !== undefined
      ? laneHeading(lanes, toggle.dataset.foldDay)
      : null);
  if (!holder) return;
  setFolded(holder, !isFolded(holder));
  announce();
};

document.addEventListener("click", (event) => {
  const toggle =
    event.target instanceof Element ? event.target.closest<HTMLElement>("[data-day-fold]") : null;
  if (toggle) toggleFrom(toggle);
});

// Jumping to an hour from the rail must land on it, so the jump unfolds the
// day it belongs to. Capture phase: the rail's own click handler scrolls to
// the slot, and a folded slot has nowhere to scroll to.
document.addEventListener(
  "click",
  (event) => {
    const link =
      event.target instanceof Element ? event.target.closest(".schedule-rail-hour") : null;
    const id = link?.getAttribute("href")?.slice(1);
    const slot = id ? document.getElementById(id) : null;
    if (!slot) return;
    const section = slot.closest<HTMLElement>("[data-schedule-day][data-folded]");
    if (section) {
      setFolded(section, false);
      announce();
    }
    const line = slot.closest<HTMLElement>("[data-lane-day]");
    const lanes = line?.closest<HTMLElement>(".room-lanes");
    const heading =
      line?.dataset.laneDay !== undefined && lanes
        ? laneHeading(lanes, line.dataset.laneDay)
        : null;
    if (heading && isFolded(heading)) {
      setFolded(heading, false);
      announce();
    }
  },
  { capture: true },
);

// Auto-fold runs once per rendered day (data-foldBound), so an htmx swap of
// the schedule region folds the fresh markup while a session-modal swap on the
// same page leaves the reader's unfolds alone. Only days with somewhere to
// unfold from fold themselves: a single-day schedule renders no toggle, and
// the rooms grid always carries the sticky bar once it has more than one day.
// A finished convention folds nothing: with every day over, the reader came
// for the archive, and a page of folded headings would hide it all.
const stillRunning = (days: HTMLElement[], today: string): boolean =>
  days.some((day) => (day.dataset.day ?? "") >= today);

const autoFold = (): void => {
  const today = eventToday();
  let folded = false;
  const sections = [...document.querySelectorAll<HTMLElement>("[data-schedule-day][data-day]")];
  for (const section of sections) {
    if ("foldBound" in section.dataset) continue;
    section.dataset.foldBound = "";
    if (!stillRunning(sections, today) || !section.querySelector("[data-day-fold]")) continue;
    if ((section.dataset.day ?? "") < today) {
      setFolded(section, true);
      folded = true;
    }
  }
  for (const heading of document.querySelectorAll<HTMLElement>("[data-day-heading][data-day]")) {
    if ("foldBound" in heading.dataset) continue;
    heading.dataset.foldBound = "";
    const lanes = heading.closest<HTMLElement>(".room-lanes");
    if (!lanes) continue;
    const siblings = [...lanes.querySelectorAll<HTMLElement>("[data-day-heading]")];
    if (siblings.length < 2 || !stillRunning(siblings, today)) continue;
    if ((heading.dataset.day ?? "") < today) {
      setFolded(heading, true);
      folded = true;
    }
  }
  if (folded) announce();
};

autoFold();
document.body.addEventListener("htmx:afterSwap", autoFold);
