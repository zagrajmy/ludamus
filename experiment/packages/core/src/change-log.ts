import { Schema } from "effect";

import {
  EventId,
  FacilitatorId,
  ScheduleChangeLogId,
  SessionId,
  SpaceId,
  UserId,
} from "./ids.js";

export const ContentFieldValue = Schema.Union([
  Schema.String,
  Schema.Int,
  Schema.Boolean,
  Schema.Array(Schema.String),
  Schema.Null,
]);

export type ContentFieldValue = typeof ContentFieldValue.Type;

export const ContentFieldChange = Schema.Struct({
  field: Schema.String,
  fieldId: Schema.NullOr(Schema.Int),
  new: ContentFieldValue,
  old: ContentFieldValue,
});

export type ContentFieldChange = typeof ContentFieldChange.Type;

export const FacilitatorChangeLogEntry = Schema.Struct({
  changes: Schema.Array(ContentFieldChange),
  creationTime: Schema.DateTimeUtc,
  eventId: EventId,
  facilitatorId: FacilitatorId,
  facilitatorName: Schema.String,
  id: Schema.Int,
  userId: Schema.NullOr(UserId),
  userName: Schema.String,
});

export type FacilitatorChangeLogEntry = typeof FacilitatorChangeLogEntry.Type;

export const NewFacilitatorChangeLog = Schema.Struct({
  changes: Schema.Array(ContentFieldChange),
  eventId: EventId,
  facilitatorId: FacilitatorId,
  userId: Schema.NullOr(UserId),
});

export type NewFacilitatorChangeLog = typeof NewFacilitatorChangeLog.Type;

export const ScheduleChangeAction = Schema.Literals([
  "assign",
  "unassign",
  "revert",
]);

export type ScheduleChangeAction = typeof ScheduleChangeAction.Type;

const Placement = {
  newEndTime: Schema.NullOr(Schema.DateTimeUtc),
  newSpaceId: Schema.NullOr(SpaceId),
  newStartTime: Schema.NullOr(Schema.DateTimeUtc),
  oldEndTime: Schema.NullOr(Schema.DateTimeUtc),
  oldSpaceId: Schema.NullOr(SpaceId),
  oldStartTime: Schema.NullOr(Schema.DateTimeUtc),
};

export const NewScheduleChangeLog = Schema.Struct({
  ...Placement,
  action: ScheduleChangeAction,
  eventId: EventId,
  movedFromId: Schema.NullOr(ScheduleChangeLogId),
  sessionId: SessionId,
  userId: Schema.NullOr(UserId),
});

export type NewScheduleChangeLog = typeof NewScheduleChangeLog.Type;

export const ScheduleChangeLogEntry = Schema.Struct({
  ...Placement,
  acknowledgedByName: Schema.String,
  acknowledgementTime: Schema.NullOr(Schema.DateTimeUtc),
  action: ScheduleChangeAction,
  creationTime: Schema.DateTimeUtc,
  eventId: EventId,
  id: ScheduleChangeLogId,
  important: Schema.Boolean,
  movedFromId: Schema.NullOr(ScheduleChangeLogId),
  newSpaceName: Schema.NullOr(Schema.String),
  oldSpaceName: Schema.NullOr(Schema.String),
  sessionId: SessionId,
  sessionTitle: Schema.String,
  userId: Schema.NullOr(UserId),
  userName: Schema.String,
});

export type ScheduleChangeLogEntry = typeof ScheduleChangeLogEntry.Type;

export const ChangeLogCursor = Schema.Struct({
  creationTime: Schema.DateTimeUtc,
  id: Schema.Int,
});

export type ChangeLogCursor = typeof ChangeLogCursor.Type;

export const CHANGE_LOG_PAGE_SIZE = 200;
