import { Context } from "effect";
import type { Effect } from "effect";

import type { EventId, SpaceId } from "../ids.js";
import type { Location, Space } from "../space.js";
import type { NotFound, StoreFailure } from "./store-error.js";

export class SpaceStore extends Context.Service<
  SpaceStore,
  {
    readonly listByEvent: (
      eventId: EventId
    ) => Effect.Effect<readonly Space[], StoreFailure>;
    readonly readInEvent: (options: {
      readonly eventId: EventId;
      readonly id: SpaceId;
    }) => Effect.Effect<Space, NotFound | StoreFailure>;
    readonly locationsByEvent: (
      eventId: EventId
    ) => Effect.Effect<ReadonlyMap<SpaceId, Location>, StoreFailure>;
  }
>()("@zagrajmy/core/SpaceStore") {}
