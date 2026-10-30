import { Schema } from "effect";

export const PromotionMode = Schema.Literals(["auto", "offer_claim"]);

export type PromotionMode = typeof PromotionMode.Type;

export const SessionParticipationStatus = Schema.Literals([
  "confirmed",
  "waiting",
  "offered",
]);

export type SessionParticipationStatus = typeof SessionParticipationStatus.Type;

export const OCCUPYING_PARTICIPATION_STATUSES: readonly SessionParticipationStatus[] =
  ["confirmed", "offered"];

export const UNLIMITED_SLOTS = 1_000_000_000;

export const WaitingParticipant = Schema.Struct({
  creationTime: Schema.DateTimeUtcFromString,
  email: Schema.String,
  fullName: Schema.String,
  hasConflict: Schema.Boolean,
  ownerSlotsRemaining: Schema.Int,
  participationId: Schema.Int,
  partyId: Schema.NullOr(Schema.Int),
  recipientUserId: Schema.Int,
  sponsorId: Schema.NullOr(Schema.Int),
  userId: Schema.Int,
});

export type WaitingParticipant = typeof WaitingParticipant.Type;

export const PromotionState = Schema.Struct({
  availableSeats: Schema.Int,
  eventSlug: Schema.String,
  offerClaimWindow: Schema.DurationFromMillis,
  presenterId: Schema.NullOr(Schema.Int),
  promotionMode: PromotionMode,
  sessionId: Schema.Int,
  sessionTitle: Schema.String,
  shadowbannedUserIds: Schema.Array(Schema.Int),
  startTime: Schema.DateTimeUtcFromString,
  waiting: Schema.Array(WaitingParticipant),
});

export type PromotionState = typeof PromotionState.Type;

export const Offer = Schema.Struct({
  eventSlug: Schema.String,
  offerExpiresAt: Schema.DateTimeUtcFromString,
  participantIds: Schema.Array(Schema.Int),
  recipients: Schema.Array(Schema.Int),
  sessionId: Schema.Int,
  sessionTitle: Schema.String,
});

export type Offer = typeof Offer.Type;

export const PromotionResult = Schema.Struct({
  offered: Schema.Array(Schema.Int),
  promoted: Schema.Array(Schema.Int),
});

export type PromotionResult = typeof PromotionResult.Type;

export const ClaimFailureReason = Schema.Literals(["not_found", "expired"]);

export type ClaimFailureReason = typeof ClaimFailureReason.Type;

export const ClaimResult = Schema.Struct({
  eventSlug: Schema.NullOr(Schema.String),
  reason: Schema.NullOr(ClaimFailureReason),
  sessionId: Schema.NullOr(Schema.Int),
  success: Schema.Boolean,
});

export type ClaimResult = typeof ClaimResult.Type;

export const SeatHoldRequest = Schema.Struct({
  actorName: Schema.String,
  partyId: Schema.NullOr(Schema.Int),
  sessionId: Schema.Int,
  sessionTitle: Schema.String,
  userId: Schema.Int,
});

export type SeatHoldRequest = typeof SeatHoldRequest.Type;

export const HeldSeatData = Schema.Struct({
  claimToken: Schema.String,
  offerExpiresAt: Schema.DateTimeUtcFromString,
  offeredAt: Schema.DateTimeUtcFromString,
  partyId: Schema.NullOr(Schema.Int),
  sessionId: Schema.Int,
  userId: Schema.Int,
});

export type HeldSeatData = typeof HeldSeatData.Type;

export const PromotionNotification = Schema.Struct({
  eventSlug: Schema.String,
  recipientUserId: Schema.Int,
  sessionId: Schema.Int,
  sessionTitle: Schema.String,
});

export type PromotionNotification = typeof PromotionNotification.Type;

export const OfferNotification = Schema.Struct({
  claimToken: Schema.String,
  eventSlug: Schema.String,
  offerExpiresAt: Schema.DateTimeUtcFromString,
  recipientUserId: Schema.Int,
  sessionId: Schema.Int,
  sessionTitle: Schema.String,
});

export type OfferNotification = typeof OfferNotification.Type;

export const HeldSeatNotification = Schema.Struct({
  actorName: Schema.String,
  claimToken: Schema.String,
  offerExpiresAt: Schema.DateTimeUtcFromString,
  recipientUserId: Schema.Int,
  sessionId: Schema.Int,
  sessionTitle: Schema.String,
});

export type HeldSeatNotification = typeof HeldSeatNotification.Type;

export const EnrollmentWindowData = Schema.Struct({
  allowAnonymousEnrollment: Schema.Boolean,
  bannerText: Schema.String,
  endTime: Schema.DateTimeUtcFromString,
  limitToEndTime: Schema.Boolean,
  maxWaitlistSessions: Schema.Int,
  percentageSlots: Schema.Int,
  restrictToConfiguredUsers: Schema.Boolean,
  startTime: Schema.DateTimeUtcFromString,
});

export type EnrollmentWindowData = typeof EnrollmentWindowData.Type;

export const EnrollmentWindow = Schema.Struct({
  ...EnrollmentWindowData.fields,
  eventId: Schema.Int,
  pk: Schema.Int,
});

export type EnrollmentWindow = typeof EnrollmentWindow.Type;

export const EnrollmentWindowRules = Schema.Struct({
  allowAnonymousEnrollment: Schema.Boolean,
  endTime: Schema.DateTimeUtcFromString,
  limitToEndTime: Schema.Boolean,
  maxWaitlistSessions: Schema.Int,
  percentageSlots: Schema.Int,
  pk: Schema.Int,
  restrictToConfiguredUsers: Schema.Boolean,
  startTime: Schema.DateTimeUtcFromString,
});

export type EnrollmentWindowRules = typeof EnrollmentWindowRules.Type;

export interface EnrollmentWindowLike {
  readonly allowAnonymousEnrollment: boolean;
  readonly maxWaitlistSessions: number;
  readonly percentageSlots: number;
  readonly restrictToConfiguredUsers: boolean;
}

export interface DatedEnrollmentWindow extends EnrollmentWindowLike {
  readonly endTime: EnrollmentWindowRules["endTime"];
  readonly pk: number;
  readonly startTime: EnrollmentWindowRules["startTime"];
}

export const EnrollmentAccess = Schema.Struct({
  openWindowIds: Schema.Array(Schema.Int),
  opensAt: Schema.NullOr(Schema.DateTimeUtcFromString),
});

export type EnrollmentAccess = typeof EnrollmentAccess.Type;

export const VirtualEnrollmentConfig = Schema.Struct({
  domain: Schema.String,
  domainSlots: Schema.Int,
  userSlots: Schema.Int,
});

export type VirtualEnrollmentConfig = typeof VirtualEnrollmentConfig.Type;

export const UserEnrollmentConfig = Schema.Struct({
  allowedSlots: Schema.Int,
  lastCheck: Schema.NullOr(Schema.DateTimeUtcFromString),
  userEmail: Schema.String,
});

export type UserEnrollmentConfig = typeof UserEnrollmentConfig.Type;
