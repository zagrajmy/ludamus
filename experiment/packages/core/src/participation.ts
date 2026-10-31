import { Schema } from "effect";

import {
  EnrollmentConfigId,
  EventId,
  ParticipationId,
  PartyId,
  SessionId,
  UserId,
} from "./ids.js";
import { UserSummary } from "./user.js";

export const ParticipationStatus = Schema.Literals([
  "confirmed",
  "waiting",
  "offered",
]);

export type ParticipationStatus = typeof ParticipationStatus.Type;

export const OCCUPYING_PARTICIPATION_STATUSES: readonly ParticipationStatus[] =
  ["confirmed", "offered"];

export const Participation = Schema.Struct({
  claimToken: Schema.String,
  claimedAt: Schema.NullOr(Schema.DateTimeUtc),
  creationTime: Schema.DateTimeUtc,
  enrolledById: Schema.NullOr(UserId),
  id: ParticipationId,
  modificationTime: Schema.DateTimeUtc,
  offerExpiresAt: Schema.NullOr(Schema.DateTimeUtc),
  offeredAt: Schema.NullOr(Schema.DateTimeUtc),
  partyId: Schema.NullOr(PartyId),
  sessionId: SessionId,
  status: ParticipationStatus,
  userId: UserId,
});

export type Participation = typeof Participation.Type;

export const ParticipationWithTimes = Schema.Struct({
  ...Participation.fields,
  agendaEndTime: Schema.NullOr(Schema.DateTimeUtc),
  agendaStartTime: Schema.NullOr(Schema.DateTimeUtc),
});

export type ParticipationWithTimes = typeof ParticipationWithTimes.Type;

export const SessionSeat = Schema.Struct({
  creationTime: Schema.DateTimeUtc,
  status: ParticipationStatus,
  user: UserSummary,
});

export type SessionSeat = typeof SessionSeat.Type;

export const SessionSeats = Schema.Struct({
  effectiveParticipantsLimit: Schema.Int,
  eligibleWindowIds: Schema.Array(EnrollmentConfigId),
  enrolledCount: Schema.Int,
  isFull: Schema.Boolean,
  participantsLimit: Schema.Int,
  seatsLeft: Schema.Int,
  sessionId: SessionId,
  waitingCount: Schema.Int,
});

export type SessionSeats = typeof SessionSeats.Type;

export const SeatRequest = Schema.Struct({
  partyId: Schema.NullOr(PartyId),
  sessionId: SessionId,
  status: ParticipationStatus,
  userId: UserId,
});

export type SeatRequest = typeof SeatRequest.Type;

export const GuestSeat = Schema.Struct({
  enrolledById: UserId,
  partyId: Schema.NullOr(PartyId),
  sessionId: SessionId,
  userId: UserId,
});

export type GuestSeat = typeof GuestSeat.Type;

export const HeldSeat = Schema.Struct({
  claimToken: Schema.String,
  offerExpiresAt: Schema.DateTimeUtc,
  offeredAt: Schema.DateTimeUtc,
  partyId: Schema.NullOr(PartyId),
  sessionId: SessionId,
  userId: UserId,
});

export type HeldSeat = typeof HeldSeat.Type;

export const OfferTerms = Schema.Struct({
  claimToken: Schema.String,
  offerExpiresAt: Schema.DateTimeUtc,
  offeredAt: Schema.DateTimeUtc,
});

export type OfferTerms = typeof OfferTerms.Type;

export const OfferedParty = Schema.Struct({
  eventSlug: Schema.String,
  members: Schema.Array(Participation),
  sessionId: SessionId,
  sessionTitle: Schema.String,
});

export type OfferedParty = typeof OfferedParty.Type;

export const EventParticipationScope = Schema.Struct({
  eventId: EventId,
  userIds: Schema.Array(UserId),
});

export type EventParticipationScope = typeof EventParticipationScope.Type;
