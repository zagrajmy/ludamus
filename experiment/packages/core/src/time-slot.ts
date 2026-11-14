import { Schema } from "effect";

import { EventId, TimeSlotId } from "./ids.js";

export const TimeSlot = Schema.Struct({
  endTime: Schema.DateTimeUtc,
  eventId: EventId,
  id: TimeSlotId,
  startTime: Schema.DateTimeUtc,
});

export type TimeSlot = typeof TimeSlot.Type;
