// Where the event's clock lives: the schedule markup stamps the event's IANA
// timezone as data-event-time-zone, and every "what time or day is it at the
// convention" question must ask that zone, never the visitor's browser.
export const eventTimeZone = (): string | undefined =>
  document.querySelector<HTMLElement>("[data-event-time-zone]")?.dataset.eventTimeZone;
