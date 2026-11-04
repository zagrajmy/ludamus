import { Context } from "effect";
import type { DateTime, Effect, Option } from "effect";

import type { EventId, ParticipationId, SessionId, UserId } from "../ids.js";
import type {
  EventParticipationScope,
  GuestSeat,
  HeldSeat,
  OfferedParty,
  OfferTerms,
  Participation,
  ParticipationStatus,
  ParticipationWithTimes,
  SeatRequest,
  SessionSeats,
} from "../participation.js";
import type { StoreFailure } from "./store-error.js";

export class ParticipationStore extends Context.Service<
  ParticipationStore,
  {
    readonly seats: (options: {
      readonly sessionIds: readonly SessionId[];
      readonly now: DateTime.Utc;
    }) => Effect.Effect<readonly SessionSeats[], StoreFailure>;
    readonly listForSession: (
      sessionId: SessionId
    ) => Effect.Effect<readonly Participation[], StoreFailure>;
    readonly listForUsersInEvent: (
      scope: EventParticipationScope
    ) => Effect.Effect<readonly ParticipationWithTimes[], StoreFailure>;
    readonly occupyingUserIds: (
      scope: EventParticipationScope
    ) => Effect.Effect<readonly UserId[], StoreFailure>;
    readonly conflictedUserIds: (options: {
      readonly sessionId: SessionId;
      readonly userIds: readonly UserId[];
    }) => Effect.Effect<readonly UserId[], StoreFailure>;
    readonly guestsEnrolledBy: (options: {
      readonly sessionId: SessionId;
      readonly enrolledById: UserId;
    }) => Effect.Effect<readonly Participation[], StoreFailure>;
    readonly upsertSeat: (
      seat: SeatRequest
    ) => Effect.Effect<Participation, StoreFailure>;
    readonly createIfAbsent: (
      seat: SeatRequest
    ) => Effect.Effect<Participation, StoreFailure>;
    readonly createGuest: (
      seat: GuestSeat
    ) => Effect.Effect<Participation, StoreFailure>;
    readonly createOffered: (
      seat: HeldSeat
    ) => Effect.Effect<Participation, StoreFailure>;
    readonly remove: (options: {
      readonly sessionId: SessionId;
      readonly userId: UserId;
    }) => Effect.Effect<Option.Option<ParticipationStatus>, StoreFailure>;
    readonly confirm: (
      ids: readonly ParticipationId[]
    ) => Effect.Effect<void, StoreFailure>;
    readonly offer: (options: {
      readonly ids: readonly ParticipationId[];
      readonly terms: OfferTerms;
    }) => Effect.Effect<void, StoreFailure>;
    readonly markClaimed: (options: {
      readonly ids: readonly ParticipationId[];
      readonly claimedAt: DateTime.Utc;
    }) => Effect.Effect<number, StoreFailure>;
    readonly dropOffered: (
      ids: readonly ParticipationId[]
    ) => Effect.Effect<number, StoreFailure>;
    readonly readOfferedParty: (options: {
      readonly sessionId: SessionId;
      readonly claimToken: string;
    }) => Effect.Effect<Option.Option<OfferedParty>, StoreFailure>;
    readonly findOfferByToken: (
      claimToken: string
    ) => Effect.Effect<Option.Option<OfferedParty>, StoreFailure>;
    readonly listLapsedOffers: (
      now: DateTime.Utc
    ) => Effect.Effect<readonly ParticipationId[], StoreFailure>;
    readonly eventIdOfSession: (
      sessionId: SessionId
    ) => Effect.Effect<Option.Option<EventId>, StoreFailure>;
  }
>()("@zagrajmy/core/ParticipationStore") {}
