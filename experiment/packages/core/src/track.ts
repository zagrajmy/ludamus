import { Schema } from "effect";

import { EventId, SpaceId, TrackId, UserId } from "./ids.js";

export const Track = Schema.Struct({
  creationTime: Schema.DateTimeUtc,
  eventId: EventId,
  id: TrackId,
  isPublic: Schema.Boolean,
  modificationTime: Schema.DateTimeUtc,
  name: Schema.String,
  slug: Schema.String,
});

export type Track = typeof Track.Type;

export const TrackListItem = Schema.Struct({
  id: TrackId,
  isPublic: Schema.Boolean,
  managerNames: Schema.Array(Schema.String),
  name: Schema.String,
  slug: Schema.String,
  spaceNames: Schema.Array(Schema.String),
});

export type TrackListItem = typeof TrackListItem.Type;

export const TrackSessionCounts = Schema.Struct({
  accepted: Schema.Int,
  onHold: Schema.Int,
  pending: Schema.Int,
  rejected: Schema.Int,
  scheduled: Schema.Int,
  trackId: TrackId,
});

export type TrackSessionCounts = typeof TrackSessionCounts.Type;

export const TrackWrite = Schema.Struct({
  isPublic: Schema.Boolean,
  managerIds: Schema.Array(UserId),
  name: Schema.String,
  slug: Schema.String,
  spaceIds: Schema.Array(SpaceId),
});

export type TrackWrite = typeof TrackWrite.Type;
