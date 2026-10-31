import { Context } from "effect";
import type { Effect } from "effect";

import type { EventId, TimeSlotId } from "../ids.js";
import type { TimeSlot } from "../time-slot.js";
import type { NotFound, StoreFailure } from "./store-error.js";

export class TimeSlotStore extends Context.Service<
  TimeSlotStore,
  {
    readonly listByEvent: (
      eventId: EventId
    ) => Effect.Effect<readonly TimeSlot[], StoreFailure>;
    readonly readInEvent: (options: {
      readonly eventId: EventId;
      readonly id: TimeSlotId;
    }) => Effect.Effect<TimeSlot, NotFound | StoreFailure>;
    readonly idsWithProposals: (
      eventId: EventId
    ) => Effect.Effect<readonly TimeSlotId[], StoreFailure>;
  }
>()("@zagrajmy/core/TimeSlotStore") {}
