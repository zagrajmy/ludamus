import { Context } from "effect";
import type { DateTime, Effect, Option } from "effect";
import type { HouseholdSeat, LockedSession, RosterPerson, SessionContext } from "../api.js";
import type { EnrollmentWrite } from "../enroll.js";
import type { EnrollmentStoreError } from "../errors.js";

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
