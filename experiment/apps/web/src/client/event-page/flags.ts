import { Schema } from "effect";

import { AvatarPerson } from "../../ui/avatar.js";

export const StatusPillIcon = Schema.Literals([
  "check-circle",
  "clock",
  "light-bulb",
  "live",
  "user-plus",
]);

export type StatusPillIcon = typeof StatusPillIcon.Type;

export const StatusPill = Schema.Struct({
  classes: Schema.String,
  icon: StatusPillIcon,
  label: Schema.String,
});

export type StatusPill = typeof StatusPill.Type;

export const EventDates = Schema.Struct({
  endIso: Schema.String,
  endShort: Schema.String,
  endTime: Schema.String,
  isSameDay: Schema.Boolean,
  startDay: Schema.String,
  startIso: Schema.String,
  startShort: Schema.String,
  startTime: Schema.String,
});

export type EventDates = typeof EventDates.Type;

export const EventHero = Schema.Struct({
  addressLines: Schema.Array(Schema.String),
  addressQuery: Schema.String,
  coverUrl: Schema.String,
  dates: EventDates,
  descriptionHtml: Schema.String,
  googleCalendarUrl: Schema.String,
  icsUrl: Schema.String,
  isEnded: Schema.Boolean,
  isLive: Schema.Boolean,
  isProposalActive: Schema.Boolean,
  isUnlisted: Schema.Boolean,
  mapsUrl: Schema.String,
  name: Schema.String,
  printUrl: Schema.String,
  proposeUrl: Schema.String,
  scheduledCount: Schema.Int,
  slug: Schema.String,
  statusPills: Schema.Array(StatusPill),
});

export type EventHero = typeof EventHero.Type;

export const LocationCrumb = Schema.Struct({
  name: Schema.String,
  spaceFilter: Schema.String,
});

export type LocationCrumb = typeof LocationCrumb.Type;

export const IconGlyph = Schema.Struct({
  paths: Schema.Array(
    Schema.Struct({
      clipRule: Schema.optionalKey(Schema.Literal("evenodd")),
      d: Schema.String,
      fillRule: Schema.optionalKey(Schema.Literal("evenodd")),
    })
  ),
  variant: Schema.Literals(["micro", "mini", "outline", "solid"]),
});

export type IconGlyph = typeof IconGlyph.Type;

export const FieldPill = Schema.Struct({
  icon: Schema.Option(IconGlyph),
  value: Schema.String,
});

export type FieldPill = typeof FieldPill.Type;

export const FieldAnswerView = Schema.Struct({
  icon: Schema.Option(IconGlyph),
  name: Schema.String,
  values: Schema.Array(Schema.String),
});

export type FieldAnswerView = typeof FieldAnswerView.Type;

export const Availability = Schema.Literals([
  "available",
  "ended",
  "full",
  "in-progress",
  "no-enrollment",
  "proposal",
  "unavailable",
]);

export type Availability = typeof Availability.Type;

export const RosterEntry = Schema.Struct({
  createdLabel: Schema.String,
  person: AvatarPerson,
  status: Schema.Literals(["confirmed", "offered", "waiting"]),
});

export type RosterEntry = typeof RosterEntry.Type;

export const SessionTiming = Schema.Struct({
  day: Schema.String,
  dayLabel: Schema.String,
  endClock: Schema.String,
  endIso: Schema.String,
  endsAt: Schema.Number,
  hour: Schema.String,
  sessionEndIso: Schema.String,
  startClock: Schema.String,
  startIso: Schema.String,
  startsAt: Schema.Number,
  when: Schema.String,
});

export type SessionTiming = typeof SessionTiming.Type;

export const SessionView = Schema.Struct({
  availability: Availability,
  bookmarkCount: Schema.Int,
  categoryName: Schema.String,
  coverUrl: Schema.String,
  crumbs: Schema.Array(LocationCrumb),
  description: Schema.String,
  descriptionHtml: Schema.String,
  durationLabel: Schema.String,
  effectiveLimit: Schema.Int,
  enrolledCount: Schema.Int,
  fieldAnswers: Schema.Array(FieldAnswerView),
  host: Schema.String,
  id: Schema.Int,
  isFull: Schema.Boolean,
  locationLabel: Schema.String,
  minAge: Schema.Int,
  overflowPills: Schema.Array(FieldPill),
  participants: Schema.Array(AvatarPerson),
  pills: Schema.Array(FieldPill),
  presenter: AvatarPerson,
  roster: Schema.Option(Schema.Array(RosterEntry)),
  seatsLabel: Schema.String,
  spaceId: Schema.String,
  spaceName: Schema.String,
  spaceOrder: Schema.String,
  spotsLeft: Schema.Int,
  spotsScarce: Schema.Boolean,
  tagCategories: Schema.String,
  tags: Schema.String,
  takesEnrollment: Schema.Boolean,
  timing: Schema.Option(SessionTiming),
  title: Schema.String,
  tracks: Schema.Array(Schema.String),
  userBookmarked: Schema.Boolean,
  userEnrolled: Schema.Boolean,
  userWaiting: Schema.Boolean,
  venueId: Schema.String,
  venueName: Schema.String,
  waitingCount: Schema.Int,
});

export type SessionView = typeof SessionView.Type;

export const CardSlot = Schema.Struct({
  dateLabel: Schema.String,
  hour: Schema.String,
  sessionIds: Schema.Array(Schema.Int),
  startsAt: Schema.Number,
});

export type CardSlot = typeof CardSlot.Type;

export const ScheduleDay = Schema.Struct({
  date: Schema.String,
  dateLabel: Schema.String,
  name: Schema.String,
  panelId: Schema.String,
  shortName: Schema.String,
});

export type ScheduleDay = typeof ScheduleDay.Type;

export const CardDay = Schema.Struct({
  day: ScheduleDay,
  slots: Schema.Array(CardSlot),
});

export type CardDay = typeof CardDay.Type;

export const LedgerTile = Schema.Struct({
  endClock: Schema.String,
  endIso: Schema.String,
  endsAt: Schema.Number,
  sessionId: Schema.Int,
  startClock: Schema.String,
  startIso: Schema.String,
  startsAt: Schema.Number,
});

export type LedgerTile = typeof LedgerTile.Type;

export const LedgerHour = Schema.Struct({
  clock: Schema.String,
  hourLabel: Schema.String,
  repeatedZone: Schema.String,
  slotKey: Schema.String,
  startsAt: Schema.Number,
  tiles: Schema.Array(LedgerTile),
});

export type LedgerHour = typeof LedgerHour.Type;

export const LedgerDay = Schema.Struct({
  day: ScheduleDay,
  endsAt: Schema.Number,
  hours: Schema.Array(LedgerHour),
  startsAt: Schema.Number,
});

export type LedgerDay = typeof LedgerDay.Type;

export const RoomColumn = Schema.Struct({
  group: Schema.String,
  groupKey: Schema.String,
  name: Schema.String,
  startsGroup: Schema.Boolean,
});

export type RoomColumn = typeof RoomColumn.Type;

export const RoomTile = Schema.Struct({
  column: Schema.Int,
  endClock: Schema.String,
  endIso: Schema.String,
  endsAt: Schema.Number,
  laneCount: Schema.Int,
  laneIndex: Schema.Int,
  sessionId: Schema.Int,
  slotKey: Schema.String,
  span: Schema.Int,
  startClock: Schema.String,
  startIso: Schema.String,
  startsAt: Schema.Number,
});

export type RoomTile = typeof RoomTile.Type;

export const RoomRow = Schema.TaggedUnion({
  DayHeading: { day: ScheduleDay, dayIndex: Schema.Int },
  Time: {
    clock: Schema.String,
    dayIndex: Schema.Int,
    endIso: Schema.String,
    endsAt: Schema.Number,
    foldUntil: Schema.String,
    isCut: Schema.Boolean,
    isFold: Schema.Boolean,
    minutes: Schema.Int,
    opensSlot: Schema.Boolean,
    repeatedZone: Schema.String,
    slotKey: Schema.String,
    startIso: Schema.String,
    startsAt: Schema.Number,
    tiles: Schema.Array(RoomTile),
  },
});

export type RoomRow = typeof RoomRow.Type;

export const RoomGrid = Schema.Struct({
  columns: Schema.Array(RoomColumn),
  days: Schema.Array(ScheduleDay),
  rows: Schema.Array(RoomRow),
});

export type RoomGrid = typeof RoomGrid.Type;

export const ScheduleLayout = Schema.TaggedUnion({
  Cards: { days: Schema.Array(CardDay), slotCount: Schema.Int },
  Compact: { days: Schema.Array(LedgerDay), rooms: RoomGrid },
});

export type ScheduleLayout = typeof ScheduleLayout.Type;

export const Choice = Schema.Struct({
  label: Schema.String,
  value: Schema.String,
});

export type Choice = typeof Choice.Type;

export const TagField = Schema.Struct({
  name: Schema.String,
  options: Schema.Array(Schema.String),
  slug: Schema.String,
});

export type TagField = typeof TagField.Type;

export const FilterChoices = Schema.Struct({
  categories: Schema.Array(Schema.String),
  days: Schema.Array(Choice),
  hosts: Schema.Array(Schema.String),
  hours: Schema.Array(Schema.String),
  minAges: Schema.Array(Schema.Int),
  minAgesDistinct: Schema.Int,
  spaces: Schema.Array(Choice),
  tagFields: Schema.Array(TagField),
  tracks: Schema.Array(Schema.String),
});

export type FilterChoices = typeof FilterChoices.Type;

export const EnrolledSession = Schema.Struct({
  id: Schema.Int,
  title: Schema.String,
  when: Schema.String,
});

export type EnrolledSession = typeof EnrolledSession.Type;

export const ScheduleView = Schema.Literals(["list", "rooms"]);

export type ScheduleView = typeof ScheduleView.Type;

export const EventPageFlags = Schema.Struct({
  choices: FilterChoices,
  enrolledSessions: Schema.Array(EnrolledSession),
  enrollmentNotices: Schema.Array(Schema.String),
  hasEnrollableSessions: Schema.Boolean,
  hero: EventHero,
  layout: ScheduleLayout,
  linkPreview: Schema.Struct({
    description: Schema.String,
    title: Schema.String,
  }),
  locale: Schema.Literals(["en", "pl"]),
  loginUrl: Schema.String,
  now: Schema.Number,
  ownProposals: Schema.Array(SessionView),
  query: Schema.String,
  sessions: Schema.Array(SessionView),
  signedIn: Schema.Boolean,
  view: ScheduleView,
});

export type EventPageFlags = typeof EventPageFlags.Type;
