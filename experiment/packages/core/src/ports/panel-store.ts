import { Context } from "effect";
import type { Effect, Option } from "effect";

import type { EventId, UserId } from "../ids.js";
import type {
  PanelRole,
  PanelStats,
  ScheduledSession,
  SphereManager,
} from "../panel/schemas.js";
import type { SphereId } from "../sphere.js";
import type { StoreFailure } from "./store-error.js";

export class PanelStore extends Context.Service<
  PanelStore,
  {
    readonly roleOf: (options: {
      readonly sphereId: SphereId;
      readonly userId: UserId;
    }) => Effect.Effect<Option.Option<PanelRole>, StoreFailure>;
    readonly eventStats: (
      eventId: EventId
    ) => Effect.Effect<PanelStats, StoreFailure>;
    readonly scheduledSessions: (
      eventId: EventId
    ) => Effect.Effect<readonly ScheduledSession[], StoreFailure>;
    readonly sphereManagers: (
      sphereId: SphereId
    ) => Effect.Effect<readonly SphereManager[], StoreFailure>;
  }
>()("@zagrajmy/core/PanelStore") {}
