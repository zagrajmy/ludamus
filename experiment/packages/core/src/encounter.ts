import { Schema } from "effect";

import { EncounterId, UserId } from "./ids.js";
import { SphereId } from "./sphere.js";

export const Encounter = Schema.Struct({
  creationTime: Schema.DateTimeUtc,
  creatorId: UserId,
  description: Schema.String,
  endTime: Schema.NullOr(Schema.DateTimeUtc),
  game: Schema.String,
  headerImage: Schema.String,
  headerImageOriginalName: Schema.String,
  id: EncounterId,
  isPublic: Schema.Boolean,
  maxParticipants: Schema.Int,
  place: Schema.String,
  rsvpCount: Schema.Int,
  shareCode: Schema.String,
  sphereId: SphereId,
  startTime: Schema.DateTimeUtc,
  title: Schema.String,
});

export type Encounter = typeof Encounter.Type;
