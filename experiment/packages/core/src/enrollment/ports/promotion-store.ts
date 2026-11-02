import { Context } from "effect";
import type { DateTime, Duration, Effect, Option } from "effect";
import type { EnrollmentStoreError } from "../errors.js";
import type { PromotionWrite } from "../promotion.js";
import type { HeldSeatData, Offer, PromotionState } from "../schemas.js";

export class PromotionStore extends Context.Service<
  PromotionStore,
  {
    readonly lockAndReadState: (
      sessionId: number
    ) => Effect.Effect<Option.Option<PromotionState>, EnrollmentStoreError>;
    readonly lockSessionRow: (
      sessionId: number
    ) => Effect.Effect<boolean, EnrollmentStoreError>;
    readonly lockOfferHolders: (
      participationIds: readonly number[]
    ) => Effect.Effect<void, EnrollmentStoreError>;
    readonly conflictedOfferIds: (query: {
      readonly sessionId: number;
      readonly participationIds: readonly number[];
    }) => Effect.Effect<readonly number[], EnrollmentStoreError>;
    readonly apply: (
      writes: readonly PromotionWrite[]
    ) => Effect.Effect<void, EnrollmentStoreError>;
    readonly createOffered: (
      seat: HeldSeatData
    ) => Effect.Effect<number, EnrollmentStoreError>;
    readonly readOfferClaimWindow: (
      sessionId: number
    ) => Effect.Effect<Duration.Duration, EnrollmentStoreError>;
    readonly readOfferByToken: (query: {
      readonly token: string;
      readonly sphereId: number;
    }) => Effect.Effect<Option.Option<Offer>, EnrollmentStoreError>;
    readonly readOfferByParticipation: (
      participationId: number
    ) => Effect.Effect<Option.Option<Offer>, EnrollmentStoreError>;
    readonly readOfferForMember: (seat: {
      readonly userId: number;
      readonly sessionId: number;
    }) => Effect.Effect<Option.Option<Offer>, EnrollmentStoreError>;
    readonly listLapsedOffers: (query: {
      readonly now: DateTime.Utc;
      readonly sphereId: number;
    }) => Effect.Effect<readonly number[], EnrollmentStoreError>;
    readonly markClaimed: (claim: {
      readonly participationIds: readonly number[];
      readonly claimedAt: DateTime.Utc;
    }) => Effect.Effect<number, EnrollmentStoreError>;
    readonly drop: (
      participationIds: readonly number[]
    ) => Effect.Effect<number, EnrollmentStoreError>;
  }
>()("@zagrajmy/core/enrollment/PromotionStore") {}
