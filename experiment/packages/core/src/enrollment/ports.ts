import { Context } from "effect";
import type { DateTime, Duration, Effect, Option } from "effect";

import type {
  HouseholdSeat,
  LockedSession,
  RosterPerson,
  SessionContext,
} from "./api.js";
import type { EnrollmentWrite } from "./enroll.js";
import type { EnrollmentStoreError, MembershipApiError } from "./errors.js";
import type { PromotionWrite } from "./promotion.js";
import type {
  EnrollmentWindow,
  EnrollmentWindowData,
  HeldSeatData,
  HeldSeatNotification,
  Offer,
  OfferNotification,
  PartyEnrolledNotification,
  PromotionNotification,
  PromotionState,
} from "./schemas.js";

export class EnrollmentTransaction extends Context.Service<
  EnrollmentTransaction,
  {
    readonly atomic: <A, E, R>(
      effect: Effect.Effect<A, E, R>
    ) => Effect.Effect<A, E | EnrollmentStoreError, R>;
  }
>()("@zagrajmy/core/enrollment/EnrollmentTransaction") {}

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

export class EnrollmentStore extends Context.Service<
  EnrollmentStore,
  {
    readonly readSessionContext: (query: {
      readonly sphereId: number;
      readonly sessionId: number;
      readonly viewerId: number;
      readonly now: DateTime.Utc;
    }) => Effect.Effect<Option.Option<SessionContext>, EnrollmentStoreError>;
    readonly readPeople: (
      userIds: readonly number[]
    ) => Effect.Effect<readonly RosterPerson[], EnrollmentStoreError>;
    readonly householdSeats: (query: {
      readonly userIds: readonly number[];
      readonly eventId: number;
    }) => Effect.Effect<readonly HouseholdSeat[], EnrollmentStoreError>;
    readonly conflictedUserIds: (query: {
      readonly sessionId: number;
      readonly userIds: readonly number[];
    }) => Effect.Effect<readonly number[], EnrollmentStoreError>;
    readonly lockSessionRow: (
      sessionId: number
    ) => Effect.Effect<boolean, EnrollmentStoreError>;
    readonly lockSeatHolders: (
      userIds: readonly number[]
    ) => Effect.Effect<void, EnrollmentStoreError>;
    readonly readSeatState: (request: {
      readonly sessionId: number;
      readonly viewerId: number;
      readonly householdUserIds: readonly number[];
      readonly now: DateTime.Utc;
    }) => Effect.Effect<Option.Option<LockedSession>, EnrollmentStoreError>;
    readonly apply: (batch: {
      readonly sessionId: number;
      readonly viewerId: number;
      readonly guestName: string;
      readonly writes: readonly EnrollmentWrite[];
    }) => Effect.Effect<void, EnrollmentStoreError>;
    readonly occupyingUserIds: (query: {
      readonly userIds: readonly number[];
      readonly eventId: number;
    }) => Effect.Effect<readonly number[], EnrollmentStoreError>;
  }
>()("@zagrajmy/core/enrollment/EnrollmentStore") {}

export class EnrollmentWindowStore extends Context.Service<
  EnrollmentWindowStore,
  {
    readonly listForEvent: (
      eventId: number
    ) => Effect.Effect<readonly EnrollmentWindow[], EnrollmentStoreError>;
    readonly read: (key: {
      readonly eventId: number;
      readonly pk: number;
    }) => Effect.Effect<Option.Option<EnrollmentWindow>, EnrollmentStoreError>;
    readonly create: (window: {
      readonly eventId: number;
      readonly data: EnrollmentWindowData;
    }) => Effect.Effect<EnrollmentWindow, EnrollmentStoreError>;
    readonly update: (window: {
      readonly eventId: number;
      readonly pk: number;
      readonly data: EnrollmentWindowData;
    }) => Effect.Effect<Option.Option<EnrollmentWindow>, EnrollmentStoreError>;
    readonly delete: (key: {
      readonly eventId: number;
      readonly pk: number;
    }) => Effect.Effect<boolean, EnrollmentStoreError>;
  }
>()("@zagrajmy/core/enrollment/EnrollmentWindowStore") {}

export class TicketApi extends Context.Service<
  TicketApi,
  {
    readonly fetchMembershipCount: (query: {
      readonly eventId: number;
      readonly email: string;
    }) => Effect.Effect<number, MembershipApiError>;
  }
>()("@zagrajmy/core/enrollment/TicketApi") {}

export class EnrollmentNotifier extends Context.Service<
  EnrollmentNotifier,
  {
    readonly notifyPromoted: (
      notification: PromotionNotification
    ) => Effect.Effect<void, EnrollmentStoreError>;
    readonly notifyOffered: (
      notification: OfferNotification
    ) => Effect.Effect<void, EnrollmentStoreError>;
    readonly notifyOfferExpired: (
      notification: PromotionNotification
    ) => Effect.Effect<void, EnrollmentStoreError>;
    readonly notifySeatHeld: (
      notification: HeldSeatNotification
    ) => Effect.Effect<void, EnrollmentStoreError>;
    readonly notifyPartyEnrolled: (
      notification: PartyEnrolledNotification
    ) => Effect.Effect<void, EnrollmentStoreError>;
  }
>()("@zagrajmy/core/enrollment/EnrollmentNotifier") {}

export class OfferExpiryScheduler extends Context.Service<
  OfferExpiryScheduler,
  {
    readonly scheduleExpiry: (expiry: {
      readonly participationId: number;
      readonly runAt: DateTime.Utc;
    }) => Effect.Effect<void, EnrollmentStoreError>;
  }
>()("@zagrajmy/core/enrollment/OfferExpiryScheduler") {}

export class ClaimTokens extends Context.Service<
  ClaimTokens,
  { readonly next: Effect.Effect<string> }
>()("@zagrajmy/core/enrollment/ClaimTokens") {}
