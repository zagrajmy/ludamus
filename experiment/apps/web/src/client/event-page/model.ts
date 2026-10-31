import { Option, Schema } from "effect";
import { defineTaggedUnion } from "foldkit/schema";

import { EnrollmentActions, enrollmentActionsFor } from "./enrollment-slot.js";
import { ComboboxId, FilterState, parseFilters } from "./filters.js";
import { EventPageFlags, RosterEntry } from "./flags.js";
import type { ScheduleView } from "./flags.js";

export const OpenCombobox = Schema.Struct({
  active: Schema.Int,
  id: ComboboxId,
  query: Schema.Option(Schema.String),
});

export type OpenCombobox = typeof OpenCombobox.Type;

export const RosterState = defineTaggedUnion({
  Failed: {},
  Loaded: { entries: Schema.Array(RosterEntry) },
  Loading: {},
});

export type RosterState = typeof RosterState.Type;

export const LoadedRoster = Schema.Struct({
  sessionId: Schema.Int,
  state: RosterState,
});

export type LoadedRoster = typeof LoadedRoster.Type;

export const EventPageModel = Schema.Struct({
  ...EventPageFlags.fields,
  combobox: Schema.Option(OpenCombobox),
  shownSession: Schema.Option(Schema.Int),
  enrollment: EnrollmentActions,
  filters: FilterState,
  foldedDays: Schema.Array(Schema.String),
  isCalendarMenuOpen: Schema.Boolean,
  isNarrow: Schema.Boolean,
  isPanelOpen: Schema.Boolean,
  openSession: Schema.Option(Schema.Int),
  rosters: Schema.Array(LoadedRoster),
});

export type EventPageModel = typeof EventPageModel.Type;

export const SESSION_DIALOG_ID = "session-dialog";

export const sessionParam = (search: string) => {
  const raw = new URLSearchParams(search).get("session") ?? "";

  return /^\d+$/u.test(raw) ? Option.some(Number(raw)) : Option.none<number>();
};

export const viewParam = (options: {
  readonly isCompact: boolean;
  readonly search: string;
}): ScheduleView =>
  options.isCompact &&
  new URLSearchParams(options.search).get("view") === "rooms"
    ? "rooms"
    : "list";

export const showsBookmarked = (flags: EventPageFlags) =>
  flags.signedIn && flags.layout._tag === "Compact";

const scheduledIds = (flags: EventPageFlags) =>
  new Set(flags.sessions.map((session) => session.id));

export const openableSession = (flags: EventPageFlags, search: string) =>
  Option.filter(sessionParam(search), (id) => scheduledIds(flags).has(id));

export const finishedDays = (flags: EventPageFlags) => {
  if (flags.layout._tag === "Cards") {
    const days = flags.layout.days;

    if (days.length < 2) {
      return [];
    }

    const open = days.filter((day) =>
      day.slots.some((slot) =>
        slot.sessionIds.some((id) =>
          flags.sessions.some(
            (session) =>
              session.id === id &&
              Option.exists(
                session.timing,
                (timing) => timing.endsAt > flags.now
              )
          )
        )
      )
    );

    return open.length === 0
      ? []
      : days.filter((day) => !open.includes(day)).map((day) => day.day.date);
  }

  const days = flags.layout.days;

  if (days.length < 2 || days.every((day) => day.endsAt <= flags.now)) {
    return [];
  }

  return days
    .filter((day) => day.endsAt <= flags.now)
    .map((day) => day.day.date);
};

export const initEventPage = (flags: EventPageFlags): EventPageModel => {
  const openSession = openableSession(flags, flags.query);

  return {
    ...flags,
    combobox: Option.none(),
    enrollment: Option.match(openSession, {
      onNone: () => EnrollmentActions.NotAvailable(),
      onSome: (sessionId) =>
        enrollmentActionsFor({
          canEnrollNow: flags.sessions.some(
            (session) =>
              session.id === sessionId &&
              (session.availability === "available" ||
                session.availability === "full")
          ),
          loginUrl: flags.loginUrl,
          sessionId,
          signedIn: flags.signedIn,
          slug: flags.hero.slug,
          takesEnrollment: flags.sessions.some(
            (session) => session.id === sessionId && session.takesEnrollment
          ),
        }),
    }),
    shownSession: openSession,
    filters: parseFilters({
      choices: flags.choices,
      search: flags.query,
      showBookmarked: showsBookmarked(flags),
    }),
    foldedDays: finishedDays(flags),
    isCalendarMenuOpen: false,
    isNarrow: false,
    isPanelOpen: false,
    openSession,
    rosters: [],
  };
};
