import { Context } from "effect";
import type { DateTime, Effect, Option } from "effect";

import type { Facilitator } from "../facilitator.js";
import type { SessionFieldAnswer, SessionFieldValueWrite } from "../fields.js";
import type {
  EventId,
  FacilitatorId,
  SessionId,
  TimeSlotId,
  TrackId,
  UserId,
} from "../ids.js";
import type {
  NewSession,
  Session,
  SessionCard,
  SessionChanges,
  SessionListFilters,
  SessionListItem,
} from "../session.js";
import type { SpaceOption } from "../space.js";
import type { TimeSlot } from "../time-slot.js";
import type { TrackSessionCounts } from "../track.js";
import type { NotFound, StoreFailure } from "./store-error.js";

export interface EventScoped<Id> {
  readonly eventId: EventId;
  readonly id: Id;
}

export class SessionStore extends Context.Service<
  SessionStore,
  {
    readonly listScheduledCards: (options: {
      readonly eventId: EventId;
      readonly now: DateTime.Utc;
      readonly rosterUpTo: number;
    }) => Effect.Effect<readonly SessionCard[], StoreFailure>;
    readonly readScheduledCard: (options: {
      readonly eventId: EventId;
      readonly sessionId: SessionId;
      readonly now: DateTime.Utc;
    }) => Effect.Effect<Option.Option<SessionCard>, StoreFailure>;
    readonly listProposalCards: (options: {
      readonly eventId: EventId;
      readonly presenterId: UserId | null;
      readonly now: DateTime.Utc;
    }) => Effect.Effect<readonly SessionCard[], StoreFailure>;
    readonly read: (
      id: SessionId
    ) => Effect.Effect<Session, NotFound | StoreFailure>;
    readonly readInEvent: (
      scope: EventScoped<SessionId>
    ) => Effect.Effect<Session, NotFound | StoreFailure>;
    readonly listByEvent: (options: {
      readonly eventId: EventId;
      readonly filters: SessionListFilters;
    }) => Effect.Effect<readonly SessionListItem[], StoreFailure>;
    readonly listDeletedByEvent: (
      eventId: EventId
    ) => Effect.Effect<readonly SessionListItem[], StoreFailure>;
    readonly listByFacilitator: (options: {
      readonly eventId: EventId;
      readonly facilitatorId: FacilitatorId;
    }) => Effect.Effect<readonly SessionListItem[], StoreFailure>;
    readonly slugExists: (options: {
      readonly eventId: EventId;
      readonly slug: string;
    }) => Effect.Effect<boolean, StoreFailure>;
    readonly create: (
      session: NewSession
    ) => Effect.Effect<SessionId, NotFound | StoreFailure>;
    readonly update: (options: {
      readonly eventId: EventId;
      readonly id: SessionId;
      readonly changes: SessionChanges;
    }) => Effect.Effect<void, NotFound | StoreFailure>;
    readonly softDelete: (
      scope: EventScoped<SessionId>
    ) => Effect.Effect<void, NotFound | StoreFailure>;
    readonly restore: (
      scope: EventScoped<SessionId>
    ) => Effect.Effect<void, NotFound | StoreFailure>;
    readonly setTracks: (options: {
      readonly eventId: EventId;
      readonly sessionId: SessionId;
      readonly trackIds: readonly TrackId[];
    }) => Effect.Effect<void, NotFound | StoreFailure>;
    readonly setTimeSlots: (options: {
      readonly eventId: EventId;
      readonly sessionId: SessionId;
      readonly timeSlotIds: readonly TimeSlotId[];
    }) => Effect.Effect<void, NotFound | StoreFailure>;
    readonly setFacilitators: (options: {
      readonly eventId: EventId;
      readonly sessionId: SessionId;
      readonly facilitatorIds: readonly FacilitatorId[];
    }) => Effect.Effect<void, NotFound | StoreFailure>;
    readonly readTrackIds: (
      sessionId: SessionId
    ) => Effect.Effect<readonly TrackId[], StoreFailure>;
    readonly readPreferredTimeSlots: (
      sessionId: SessionId
    ) => Effect.Effect<readonly TimeSlot[], StoreFailure>;
    readonly readSpaceOptions: (
      sessionId: SessionId
    ) => Effect.Effect<readonly SpaceOption[], StoreFailure>;
    readonly facilitatorsBySession: (
      sessionIds: readonly SessionId[]
    ) => Effect.Effect<
      ReadonlyMap<SessionId, readonly Facilitator[]>,
      StoreFailure
    >;
    readonly saveFieldValues: (options: {
      readonly sessionId: SessionId;
      readonly values: readonly SessionFieldValueWrite[];
    }) => Effect.Effect<void, StoreFailure>;
    readonly readFieldValues: (
      sessionId: SessionId
    ) => Effect.Effect<readonly SessionFieldAnswer[], StoreFailure>;
    readonly countByTrack: (
      eventId: EventId
    ) => Effect.Effect<readonly TrackSessionCounts[], StoreFailure>;
  }
>()("@zagrajmy/core/SessionStore") {}
