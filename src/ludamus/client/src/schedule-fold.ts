// Folding days across the schedule layouts. A day heading doubles as a
// disclosure button ([data-day-fold]): the ledger and the card grid fold their
// [data-schedule-day] section (CSS hides its slots), the rooms grid marks its
// [data-day-heading] folded and room-lanes.ts collapses the day's tracks. Days
// whose local date is already behind the event's today arrive folded —
// yesterday's programme is one click away, not in the way. Fold state is a
// reading gesture: nothing of it reaches the URL or the filters.

import { eventTimeZone } from "./event-time";

const announce = (): void => {
  document.dispatchEvent(new CustomEvent("schedule:filtered"));
};

// The event's calendar date decides what counts as "already over": visiting on
// Saturday folds Friday, whatever the visitor's own timezone says. en-CA is
// the locale whose date format is exactly YYYY-MM-DD, so the result compares
// against the served data-day stamps as a plain string.
const eventToday = (): string => {
  const timeZone = eventTimeZone();
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

// A jump must land on its slot, and a folded slot has nowhere to scroll to.
// The rail announces every jump — tap or scrub alike — as a schedule:jump
// bubbling from the target slot (event-timeline.ts), synchronously before it
// scrolls, so the day is open again by the time the scroll runs.
document.addEventListener("schedule:jump", (event) => {
  const slot = event.target instanceof Element ? event.target : null;
  if (!slot) return;
  const section = slot.closest<HTMLElement>("[data-schedule-day][data-folded]");
  if (section) {
    setFolded(section, false);
    announce();
  }
  const line = slot.closest<HTMLElement>("[data-lane-day]");
  const lanes = line?.closest<HTMLElement>(".room-lanes");
  const heading =
    line?.dataset.laneDay !== undefined && lanes ? laneHeading(lanes, line.dataset.laneDay) : null;
  if (heading && isFolded(heading)) {
    setFolded(heading, false);
    announce();
  }
});

// Auto-fold runs once per rendered day (data-foldBound), so an htmx swap of
// the schedule region folds the fresh markup while a session-modal swap on the
// same page leaves the reader's unfolds alone. A whole fold scope — the page's
// day sections, or one rooms grid's day headings — stays open when it has a
// single day (nothing to fold behind) or when every day is over: a finished
// convention is an archive, and a page of folded headings would hide it all.
const foldPastDays = (holders: HTMLElement[], today: string): boolean => {
  const fresh = holders.filter((holder) => !("foldBound" in holder.dataset));
  for (const holder of fresh) holder.dataset.foldBound = "";
  if (holders.length < 2 || !holders.some((holder) => (holder.dataset.day ?? "") >= today)) {
    return false;
  }
  const past = fresh.filter((holder) => (holder.dataset.day ?? "") < today);
  for (const holder of past) setFolded(holder, true);
  return past.length > 0;
};

const autoFold = (): void => {
  const today = eventToday();
  let folded = foldPastDays(
    [...document.querySelectorAll<HTMLElement>("[data-schedule-day][data-day]")],
    today,
  );
  for (const lanes of document.querySelectorAll<HTMLElement>(".room-lanes")) {
    folded =
      foldPastDays(
        [...lanes.querySelectorAll<HTMLElement>("[data-day-heading][data-day]")],
        today,
      ) || folded;
  }
  if (folded) announce();
};

autoFold();
document.body.addEventListener("htmx:afterSwap", autoFold);
