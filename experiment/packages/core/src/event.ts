import { Schema } from "effect";

import { SphereId } from "./sphere.js";

export const EventId = Schema.Int.pipe(Schema.brand("EventId"));
export type EventId = typeof EventId.Type;

export const EventSummary = Schema.Struct({
  endTime: Schema.String,
  id: EventId,
  name: Schema.String,
  slug: Schema.String,
  sphereId: SphereId,
  startTime: Schema.String,
});
export type EventSummary = typeof EventSummary.Type;
