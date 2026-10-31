import { Schema } from "effect";

import { AgendaItem } from "./agenda-item.js";
import { SessionFieldAnswer } from "./fields.js";
import {
  EventId,
  FacilitatorId,
  ProposalCategoryId,
  SessionFieldId,
  SessionId,
  TimeSlotId,
  TrackId,
  UserId,
} from "./ids.js";
import { SessionSeat, SessionSeats } from "./participation.js";
import { Location } from "./space.js";
import { TimeSlot } from "./time-slot.js";
import { UserSummary } from "./user.js";

export const SessionStatus = Schema.Literals([
  "pending",
  "accepted",
  "on_hold",
  "rejected",
]);

export type SessionStatus = typeof SessionStatus.Type;

export const Session = Schema.Struct({
  categoryId: Schema.NullOr(ProposalCategoryId),
  contactEmail: Schema.String,
  coverImage: Schema.String,
  coverImageOriginalName: Schema.String,
  creationTime: Schema.DateTimeUtc,
  deletedAt: Schema.NullOr(Schema.DateTimeUtc),
  description: Schema.String,
  duration: Schema.String,
  eventId: EventId,
  facilitatorName: Schema.String,
  id: SessionId,
  ident: Schema.String,
  minAge: Schema.Int,
  modificationTime: Schema.DateTimeUtc,
  participantsLimit: Schema.Int,
  presenterId: Schema.NullOr(UserId),
  scheduleConfirmed: Schema.Boolean,
  slug: Schema.String,
  status: SessionStatus,
  title: Schema.String,
});

export type Session = typeof Session.Type;

export const SessionListItem = Schema.Struct({
  categoryName: Schema.String,
  creationTime: Schema.DateTimeUtc,
  facilitatorName: Schema.String,
  id: SessionId,
  isDeleted: Schema.Boolean,
  isScheduled: Schema.Boolean,
  status: SessionStatus,
  title: Schema.String,
});

export type SessionListItem = typeof SessionListItem.Type;

export const SessionSortKey = Schema.Literals([
  "title",
  "host",
  "category",
  "status",
  "created",
]);

export type SessionSortKey = typeof SessionSortKey.Type;

export const SessionSort = Schema.Union([
  Schema.Struct({
    descending: Schema.Boolean,
    key: SessionSortKey,
  }),
  Schema.Struct({
    descending: Schema.Boolean,
    fieldId: SessionFieldId,
  }),
]);

export type SessionSort = typeof SessionSort.Type;

export const SessionFieldFilter = Schema.Struct({
  fieldId: SessionFieldId,
  value: Schema.String,
});

export type SessionFieldFilter = typeof SessionFieldFilter.Type;

export const SessionListFilters = Schema.Struct({
  categoryId: Schema.optionalKey(ProposalCategoryId),
  fieldFilters: Schema.optionalKey(Schema.Array(SessionFieldFilter)),
  multiTracks: Schema.optionalKey(Schema.Boolean),
  scheduled: Schema.optionalKey(Schema.Boolean),
  search: Schema.optionalKey(Schema.String),
  sort: Schema.optionalKey(SessionSort),
  status: Schema.optionalKey(SessionStatus),
  trackId: Schema.optionalKey(TrackId),
});

export type SessionListFilters = typeof SessionListFilters.Type;

export const NewSession = Schema.Struct({
  categoryId: Schema.NullOr(ProposalCategoryId),
  contactEmail: Schema.String,
  description: Schema.String,
  duration: Schema.String,
  eventId: EventId,
  facilitatorIds: Schema.Array(FacilitatorId),
  facilitatorName: Schema.String,
  ident: Schema.String,
  minAge: Schema.Int,
  participantsLimit: Schema.Int,
  presenterId: Schema.NullOr(UserId),
  scheduleConfirmed: Schema.Boolean,
  slug: Schema.String,
  status: SessionStatus,
  timeSlotIds: Schema.Array(TimeSlotId),
  title: Schema.String,
  trackIds: Schema.Array(TrackId),
});

export type NewSession = typeof NewSession.Type;

export const SessionChanges = Schema.Struct({
  categoryId: Schema.optionalKey(Schema.NullOr(ProposalCategoryId)),
  contactEmail: Schema.optionalKey(Schema.String),
  description: Schema.optionalKey(Schema.String),
  duration: Schema.optionalKey(Schema.String),
  facilitatorName: Schema.optionalKey(Schema.String),
  minAge: Schema.optionalKey(Schema.Int),
  participantsLimit: Schema.optionalKey(Schema.Int),
  scheduleConfirmed: Schema.optionalKey(Schema.Boolean),
  slug: Schema.optionalKey(Schema.String),
  status: Schema.optionalKey(SessionStatus),
  title: Schema.optionalKey(Schema.String),
});

export type SessionChanges = typeof SessionChanges.Type;

export const SessionCard = Schema.Struct({
  agendaItem: Schema.NullOr(AgendaItem),
  categoryName: Schema.String,
  fieldValues: Schema.Array(SessionFieldAnswer),
  location: Location,
  participations: Schema.Array(SessionSeat),
  preferredTimeSlots: Schema.Array(TimeSlot),
  presenter: Schema.NullOr(UserSummary),
  seats: SessionSeats,
  session: Session,
  trackNames: Schema.Array(Schema.String),
});

export type SessionCard = typeof SessionCard.Type;
