import { Schema } from "effect";

import { NamedId } from "../schemas.js";

export const TrackRow = Schema.Struct({
  isPublic: Schema.Boolean,
  managerNames: Schema.Array(Schema.String),
  name: Schema.String,
  slug: Schema.String,
  spaceNames: Schema.Array(Schema.String),
});

export type TrackRow = typeof TrackRow.Type;

export const TracksFlags = Schema.Struct({
  eventSlug: Schema.String,
  tracks: Schema.Array(TrackRow),
});

export type TracksFlags = typeof TracksFlags.Type;

export const TrackFormValues = Schema.Struct({
  isPublic: Schema.Boolean,
  managerIds: Schema.Array(Schema.Int),
  name: Schema.String,
  spaceIds: Schema.Array(Schema.Int),
});

export type TrackFormValues = typeof TrackFormValues.Type;

export const TrackFormFlags = Schema.Struct({
  eventSlug: Schema.String,
  managers: Schema.Array(NamedId),
  spaces: Schema.Array(NamedId),
  trackSlug: Schema.OptionFromOptional(Schema.String),
  values: TrackFormValues,
});

export type TrackFormFlags = typeof TrackFormFlags.Type;
