import { Context } from "effect";
import type { DateTime, Effect, Option } from "effect";

import type { AgendaItem, NewAgendaItem } from "../agenda-item.js";
import type { AgendaItemId, EventId, SessionId, SpaceId } from "../ids.js";
import type { NotFound, StoreFailure } from "./store-error.js";

export class AgendaItemStore extends Context.Service<
  AgendaItemStore,
  {
    readonly readBySession: (
      sessionId: SessionId
    ) => Effect.Effect<Option.Option<AgendaItem>, StoreFailure>;
    readonly listOverlappingInSpace: (options: {
      readonly spaceId: SpaceId;
      readonly startTime: DateTime.Utc;
      readonly endTime: DateTime.Utc;
      readonly excludeSessionId: SessionId | null;
    }) => Effect.Effect<readonly AgendaItem[], StoreFailure>;
    readonly create: (
      item: NewAgendaItem
    ) => Effect.Effect<AgendaItemId, StoreFailure>;
    readonly delete: (options: {
      readonly eventId: EventId;
      readonly id: AgendaItemId;
    }) => Effect.Effect<void, NotFound | StoreFailure>;
  }
>()("@zagrajmy/core/AgendaItemStore") {}
