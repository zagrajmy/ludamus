import { Schema } from "effect";

import { EventId, SpaceId } from "./ids.js";

export const SPACE_MAX_DEPTH = 7;

export const Space = Schema.Struct({
  capacity: Schema.NullOr(Schema.Int),
  creationTime: Schema.DateTimeUtc,
  description: Schema.String,
  eventId: EventId,
  id: SpaceId,
  location: Schema.String,
  modificationTime: Schema.DateTimeUtc,
  name: Schema.String,
  order: Schema.Int,
  parentId: Schema.NullOr(SpaceId),
  programmeOrder: Schema.Int,
  slug: Schema.String,
});

export type Space = typeof Space.Type;

export const SortPathStep = Schema.Struct({
  id: SpaceId,
  name: Schema.String,
  order: Schema.Int,
});

export type SortPathStep = typeof SortPathStep.Type;

export const Location = Schema.Struct({
  parentId: Schema.Int,
  parentName: Schema.String,
  path: Schema.String,
  programmeOrder: Schema.Int,
  sortPath: Schema.Array(SortPathStep),
  spaceId: Schema.Int,
  spaceName: Schema.String,
});

export type Location = typeof Location.Type;

export const NO_LOCATION: Location = {
  parentId: 0,
  parentName: "",
  path: "",
  programmeOrder: 0,
  sortPath: [],
  spaceId: 0,
  spaceName: "",
};

export const SpaceOption = Schema.Struct({
  group: Schema.String,
  id: SpaceId,
  name: Schema.String,
});

export type SpaceOption = typeof SpaceOption.Type;
