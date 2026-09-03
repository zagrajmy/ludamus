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
