import { Schema } from "effect";

import { ParticipationStatus } from "../participation.js";
import { EnrollmentWindowPolicy, ExistingParticipation } from "./enroll.js";
import { EnrollFooter } from "./footer.js";
import { EnrollmentNotice } from "./refusals.js";
import { EnrollmentWindowRules } from "./schemas.js";

export const AgendaSlot = Schema.Struct({
  endTime: Schema.DateTimeUtcFromString,
  spaceName: Schema.NullOr(Schema.String),
  startTime: Schema.DateTimeUtcFromString,
});

export type AgendaSlot = typeof AgendaSlot.Type;

export const SessionSeatCounts = Schema.Struct({
  effectiveParticipantsLimit: Schema.Int,
  eligibleWindowIds: Schema.Array(Schema.Int),
  enrolledCount: Schema.Int,
  isFull: Schema.Boolean,
  seatsLeft: Schema.Int,
  waitingCount: Schema.Int,
});

export type SessionSeatCounts = typeof SessionSeatCounts.Type;

export const PersonFace = Schema.Struct({
  avatarUrl: Schema.String,
  email: Schema.String,
  name: Schema.String,
  useGravatar: Schema.Boolean,
});

export type PersonFace = typeof PersonFace.Type;

export const SessionContext = Schema.Struct({
  agenda: Schema.NullOr(AgendaSlot),
  description: Schema.String,
  eventCoverImage: Schema.String,
  eventId: Schema.Int,
  eventName: Schema.String,
  eventSlug: Schema.String,
  facilitatorName: Schema.String,
  isPubliclyScheduled: Schema.Boolean,
  minAge: Schema.Int,
  participantsLimit: Schema.Int,
  presenter: Schema.NullOr(PersonFace),
  presenterId: Schema.NullOr(Schema.Int),
  seats: SessionSeatCounts,
  sessionCoverImage: Schema.String,
  sessionId: Schema.Int,
  title: Schema.String,
  viewerBanned: Schema.Boolean,
  viewerGuestCount: Schema.Int,
  viewerHasParticipation: Schema.Boolean,
  viewerShadowbanned: Schema.Boolean,
  windows: Schema.Array(EnrollmentWindowRules),
});

export type SessionContext = typeof SessionContext.Type;

export const RosterPerson = Schema.Struct({
  ...PersonFace.fields,
  id: Schema.Int,
  isActive: Schema.Boolean,
  slug: Schema.String,
});

export type RosterPerson = typeof RosterPerson.Type;

export const HouseholdSeat = Schema.Struct({
  endTime: Schema.NullOr(Schema.DateTimeUtcFromString),
  hasAgenda: Schema.Boolean,
  sessionId: Schema.Int,
  startTime: Schema.NullOr(Schema.DateTimeUtcFromString),
  status: ParticipationStatus,
  userId: Schema.Int,
});

export type HouseholdSeat = typeof HouseholdSeat.Type;

export const ShadowbanNotice = Schema.Struct({
  person: PersonFace,
  shadowbannedAt: Schema.DateTimeUtcFromString,
});

export type ShadowbanNotice = typeof ShadowbanNotice.Type;

export const LockedSession = Schema.Struct({
  conflictedUserIds: Schema.Array(Schema.Int),
  eligibleWindows: Schema.Array(EnrollmentWindowPolicy),
  enrolledCount: Schema.Int,
  eventId: Schema.Int,
  eventSlug: Schema.String,
  guestParticipationIds: Schema.Array(Schema.Int),
  participantsLimit: Schema.Int,
  participations: Schema.Array(ExistingParticipation),
  presenterId: Schema.NullOr(Schema.Int),
  shadowbannedUserIds: Schema.Array(Schema.Int),
  title: Schema.String,
});

export type LockedSession = typeof LockedSession.Type;

export const BadgeVariant = Schema.Literals([
  "success",
  "warning",
  "danger",
  "muted",
]);

export type BadgeVariant = typeof BadgeVariant.Type;

export const EnrollmentRow = Schema.Struct({
  badge: Schema.Struct({ label: Schema.String, variant: BadgeVariant }),
  boxChecked: Schema.Boolean,
  checked: Schema.Boolean,
  disabled: Schema.Boolean,
  isViewer: Schema.Boolean,
  needsApproval: Schema.Boolean,
  occupiesSeat: Schema.Boolean,
  person: PersonFace,
  reason: Schema.String,
  userId: Schema.Int,
});

export type EnrollmentRow = typeof EnrollmentRow.Type;

export const PartyChoice = Schema.Struct({
  id: Schema.Int,
  isOwnLed: Schema.Boolean,
  leaderName: Schema.String,
  name: Schema.String,
});

export type PartyChoice = typeof PartyChoice.Type;

export const EnrollmentForm = Schema.Struct({
  agenda: Schema.NullOr(AgendaSlot),
  ctaLabel: Schema.String,
  description: Schema.String,
  eventCoverImage: Schema.String,
  eventName: Schema.String,
  eventSlug: Schema.String,
  facilitatorName: Schema.String,
  guests: Schema.NullOr(Schema.Struct({ count: Schema.Int, max: Schema.Int })),
  minAge: Schema.Int,
  partyChoices: Schema.Array(PartyChoice),
  presenter: Schema.NullOr(PersonFace),
  rows: Schema.Array(EnrollmentRow),
  seats: SessionSeatCounts,
  selectedPartyId: Schema.NullOr(Schema.Int),
  sessionCoverImage: Schema.String,
  sessionId: Schema.Int,
  shadowbanWarnings: Schema.Array(ShadowbanNotice),
  title: Schema.String,
});

export type EnrollmentForm = typeof EnrollmentForm.Type;

export const ReadEnrollmentFormInput = Schema.Struct({
  party: Schema.NullOr(Schema.String),
  sessionId: Schema.Int,
});

export type ReadEnrollmentFormInput = typeof ReadEnrollmentFormInput.Type;

export const PersonChoice = Schema.Struct({
  userId: Schema.Int,
  value: Schema.String,
});

export type PersonChoice = typeof PersonChoice.Type;

export const SubmitEnrollmentsInput = Schema.Struct({
  choices: Schema.Array(PersonChoice),
  guests: Schema.NullOr(Schema.Int),
  mode: Schema.Literals(["desired", "explicit"]),
  party: Schema.NullOr(Schema.String),
  sessionId: Schema.Int,
});

export type SubmitEnrollmentsInput = typeof SubmitEnrollmentsInput.Type;

export const SubmittedEnrollments = Schema.Struct({
  eventSlug: Schema.String,
  footer: EnrollFooter,
  notices: Schema.Array(EnrollmentNotice),
  seats: SessionSeatCounts,
  sessionId: Schema.Int,
});

export type SubmittedEnrollments = typeof SubmittedEnrollments.Type;

export const ReadEnrollFooterInput = Schema.Struct({
  sessionIds: Schema.Array(Schema.Int),
});

export const SessionFooter = Schema.Struct({
  eventSlug: Schema.String,
  footer: EnrollFooter,
  seats: SessionSeatCounts,
  sessionId: Schema.Int,
  viewerId: Schema.Int,
});

export type SessionFooter = typeof SessionFooter.Type;

export const OfferTokenInput = Schema.Struct({ token: Schema.String });

export const OfferView = Schema.Struct({
  eventSlug: Schema.String,
  offerExpiresAt: Schema.DateTimeUtcFromString,
  sessionId: Schema.Int,
  sessionTitle: Schema.String,
});

export type OfferView = typeof OfferView.Type;

export const OfferResolution = Schema.Struct({
  eventSlug: Schema.NullOr(Schema.String),
  outcome: Schema.Literals([
    "claimed",
    "declined",
    "not_found",
    "expired",
    "conflict",
  ]),
  sessionId: Schema.NullOr(Schema.Int),
});

export type OfferResolution = typeof OfferResolution.Type;

export const ExpiredOffers = Schema.Struct({
  expired: Schema.Int,
  promoted: Schema.Int,
});

export type ExpiredOffers = typeof ExpiredOffers.Type;

export const BookmarkInput = Schema.Struct({ sessionId: Schema.Int });

export const BookmarkToggled = Schema.Struct({
  bookmarked: Schema.Boolean,
  count: Schema.Int,
});

export {
  EnrollmentNotice,
  EnrollmentRefused,
  MessageItem,
  MessageLevel,
  RefusalDestination,
} from "./refusals.js";

export { LoginRequired } from "./login-required.js";
