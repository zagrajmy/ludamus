import { Schema } from "effect";

import { EventId, FacilitatorId, UserId } from "./ids.js";

export const AccreditationType = Schema.Literals([
  "none",
  "standard",
  "guest",
  "honorary",
  "creator",
]);

export type AccreditationType = typeof AccreditationType.Type;

export const Facilitator = Schema.Struct({
  accreditationType: AccreditationType,
  deletedAt: Schema.NullOr(Schema.DateTimeUtc),
  displayName: Schema.String,
  eventId: EventId,
  guildId: Schema.NullOr(Schema.Int),
  id: FacilitatorId,
  ident: Schema.String,
  internalComment: Schema.String,
  isCollective: Schema.Boolean,
  organizerId: Schema.NullOr(UserId),
  organizerName: Schema.NullOr(Schema.String),
  slug: Schema.String,
  userId: Schema.NullOr(UserId),
});

export type Facilitator = typeof Facilitator.Type;

export const FacilitatorListItem = Schema.Struct({
  accreditationType: AccreditationType,
  deletedAt: Schema.NullOr(Schema.DateTimeUtc),
  displayName: Schema.String,
  id: FacilitatorId,
  organizerId: Schema.NullOr(UserId),
  organizerName: Schema.NullOr(Schema.String),
  sessionCount: Schema.Int,
  slug: Schema.String,
  userId: Schema.NullOr(UserId),
});

export type FacilitatorListItem = typeof FacilitatorListItem.Type;

export const FacilitatorSort = Schema.Literals([
  "name",
  "-name",
  "accreditation",
  "-accreditation",
  "sessions",
  "-sessions",
  "linked",
  "-linked",
  "organizer",
  "-organizer",
]);

export type FacilitatorSort = typeof FacilitatorSort.Type;

export const FacilitatorListFilters = Schema.Struct({
  accreditation: Schema.optionalKey(AccreditationType),
  ids: Schema.optionalKey(Schema.Array(FacilitatorId)),
  limit: Schema.optionalKey(Schema.Int),
  organizerId: Schema.optionalKey(UserId),
  organizerUnassigned: Schema.optionalKey(Schema.Boolean),
  search: Schema.optionalKey(Schema.String),
  sort: Schema.optionalKey(FacilitatorSort),
});

export type FacilitatorListFilters = typeof FacilitatorListFilters.Type;

export const NewFacilitator = Schema.Struct({
  accreditationType: AccreditationType,
  displayName: Schema.String,
  eventId: EventId,
  ident: Schema.String,
  isCollective: Schema.Boolean,
  organizerId: Schema.NullOr(UserId),
  slug: Schema.String,
  userId: Schema.NullOr(UserId),
});

export type NewFacilitator = typeof NewFacilitator.Type;

export const FacilitatorChanges = Schema.Struct({
  accreditationType: Schema.optionalKey(AccreditationType),
  displayName: Schema.optionalKey(Schema.String),
  guildId: Schema.optionalKey(Schema.NullOr(Schema.Int)),
  internalComment: Schema.optionalKey(Schema.String),
  isCollective: Schema.optionalKey(Schema.Boolean),
  organizerId: Schema.optionalKey(Schema.NullOr(UserId)),
  userId: Schema.optionalKey(Schema.NullOr(UserId)),
});

export type FacilitatorChanges = typeof FacilitatorChanges.Type;

export const FacilitatorSessionCounts = Schema.Struct({
  deleted: Schema.Int,
  live: Schema.Int,
});

export type FacilitatorSessionCounts = typeof FacilitatorSessionCounts.Type;
