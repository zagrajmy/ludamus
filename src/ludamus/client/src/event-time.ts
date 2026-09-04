// Where the event's clock lives: the schedule markup stamps the event's IANA
// timezone as data-event-time-zone, and every "what time or day is it at the
// convention" question must ask that zone, never the visitor's browser.
export const eventTimeZone = (): string | undefined =>
  document.querySelector<HTMLElement>("[data-event-time-zone]")?.dataset.eventTimeZone;

// Where the event's days turn over: the same markup stamps the hour the
// programme day opens (data-day-starts-at), because a convention day ends when
// people go to sleep, not at midnight. A reader at 02:00 is still on
// yesterday's programme day.
export const programmeDayStartHour = (): number =>
  Number(document.querySelector<HTMLElement>("[data-day-starts-at]")?.dataset.dayStartsAt ?? 0);

// The programme date holding an instant, as YYYY-MM-DD in the event's zone:
// the calendar date, stepped back one day while the wall clock is still
// before the turnover. Read off the zone's wall clock rather than by shifting
// the instant — across a clock change the hours before the turnover are not
// six hours of elapsed time. en-CA is the locale whose date format is exactly
// YYYY-MM-DD, so the result compares against served data-day stamps as a
// plain string.
export const programmeDate = (
  at: number,
  timeZone: string | undefined,
  dayStartHour: number,
): string => {
  const parts = new Intl.DateTimeFormat("en-CA", {
    ...(timeZone ? { timeZone } : {}),
    day: "2-digit",
    hour: "2-digit",
    hourCycle: "h23",
    month: "2-digit",
    year: "numeric",
  }).formatToParts(at);
  const part = (type: Intl.DateTimeFormatPartTypes): number =>
    Number(parts.find((candidate) => candidate.type === type)?.value ?? 0);
  // UTC arithmetic on a date-only value has no clock change to trip over.
  const midnight = Date.UTC(part("year"), part("month") - 1, part("day"));
  const opened = part("hour") >= dayStartHour ? midnight : midnight - 24 * 60 * 60 * 1000;
  return new Date(opened).toISOString().slice(0, 10);
};
