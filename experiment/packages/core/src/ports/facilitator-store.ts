import { Context } from "effect";
import type { Effect, Option } from "effect";

import type {
  AccreditationType,
  Facilitator,
  FacilitatorChanges,
  FacilitatorListFilters,
  FacilitatorListItem,
  FacilitatorSessionCounts,
  NewFacilitator,
} from "../facilitator.js";
import type { EventId, FacilitatorId, UserId } from "../ids.js";
import type { NotFound, StoreFailure } from "./store-error.js";

export interface FacilitatorScope {
  readonly eventId: EventId;
  readonly id: FacilitatorId;
}

export class FacilitatorStore extends Context.Service<
  FacilitatorStore,
  {
    readonly create: (
      facilitator: NewFacilitator
    ) => Effect.Effect<Facilitator, StoreFailure>;
    readonly readInEvent: (
      scope: FacilitatorScope
    ) => Effect.Effect<Facilitator, NotFound | StoreFailure>;
    readonly readBySlug: (options: {
      readonly eventId: EventId;
      readonly slug: string;
    }) => Effect.Effect<Facilitator, NotFound | StoreFailure>;
    readonly readBySlugIncludingDeleted: (options: {
      readonly eventId: EventId;
      readonly slug: string;
    }) => Effect.Effect<Facilitator, NotFound | StoreFailure>;
    readonly findByUser: (options: {
      readonly eventId: EventId;
      readonly userId: UserId;
    }) => Effect.Effect<Option.Option<Facilitator>, StoreFailure>;
    readonly findByDisplayName: (options: {
      readonly eventId: EventId;
      readonly displayName: string;
    }) => Effect.Effect<Option.Option<Facilitator>, StoreFailure>;
    readonly slugExists: (options: {
      readonly eventId: EventId;
      readonly slug: string;
    }) => Effect.Effect<boolean, StoreFailure>;
    readonly listByEvent: (options: {
      readonly eventId: EventId;
      readonly filters: FacilitatorListFilters;
    }) => Effect.Effect<readonly FacilitatorListItem[], StoreFailure>;
    readonly listDeletedByEvent: (
      eventId: EventId
    ) => Effect.Effect<readonly FacilitatorListItem[], StoreFailure>;
    readonly update: (options: {
      readonly eventId: EventId;
      readonly id: FacilitatorId;
      readonly changes: FacilitatorChanges;
    }) => Effect.Effect<Facilitator, NotFound | StoreFailure>;
    readonly setAccreditation: (options: {
      readonly eventId: EventId;
      readonly ids: readonly FacilitatorId[];
      readonly accreditationType: AccreditationType;
    }) => Effect.Effect<number, StoreFailure>;
    readonly claim: (options: {
      readonly eventId: EventId;
      readonly id: FacilitatorId;
      readonly organizerId: UserId;
    }) => Effect.Effect<boolean, StoreFailure>;
    readonly release: (options: {
      readonly eventId: EventId;
      readonly id: FacilitatorId;
      readonly organizerId: UserId | null;
    }) => Effect.Effect<boolean, StoreFailure>;
    readonly countSessions: (
      scope: FacilitatorScope
    ) => Effect.Effect<FacilitatorSessionCounts, StoreFailure>;
    readonly softDelete: (
      scope: FacilitatorScope
    ) => Effect.Effect<void, NotFound | StoreFailure>;
    readonly restore: (
      scope: FacilitatorScope
    ) => Effect.Effect<void, NotFound | StoreFailure>;
  }
>()("@zagrajmy/core/FacilitatorStore") {}
