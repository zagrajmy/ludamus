import { Context } from "effect";
import type { DateTime, Effect } from "effect";

import type {
  Event,
  EventListItem,
  EventProposalSettings,
  EventSummary,
} from "../event.js";
import type { EventId } from "../ids.js";
import type { SphereId } from "../sphere.js";
import type { NotFound, StoreFailure } from "./store-error.js";

export { StoreError } from "./store-error.js";

export class EventStore extends Context.Service<
  EventStore,
  {
    readonly listPublished: (
      sphereId: SphereId
    ) => Effect.Effect<readonly EventSummary[], StoreFailure>;
    readonly listForFeed: (options: {
      readonly sphereId: SphereId;
      readonly now: DateTime.Utc;
      readonly includeHidden: boolean;
    }) => Effect.Effect<readonly EventListItem[], StoreFailure>;
    readonly listBySphere: (
      sphereId: SphereId
    ) => Effect.Effect<readonly Event[], StoreFailure>;
    readonly read: (
      id: EventId
    ) => Effect.Effect<Event, NotFound | StoreFailure>;
    readonly readInSphere: (options: {
      readonly sphereId: SphereId;
      readonly id: EventId;
    }) => Effect.Effect<Event, NotFound | StoreFailure>;
    readonly readBySlug: (options: {
      readonly sphereId: SphereId;
      readonly slug: string;
    }) => Effect.Effect<Event, NotFound | StoreFailure>;
    readonly readProposalSettings: (
      eventId: EventId
    ) => Effect.Effect<EventProposalSettings, StoreFailure>;
  }
>()("@zagrajmy/core/EventStore") {}
