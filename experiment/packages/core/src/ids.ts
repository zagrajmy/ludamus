import { Schema } from "effect";

export const AgendaItemId = Schema.Int.pipe(Schema.brand("AgendaItemId"));

export type AgendaItemId = typeof AgendaItemId.Type;

export const AnnouncementId = Schema.Int.pipe(Schema.brand("AnnouncementId"));

export type AnnouncementId = typeof AnnouncementId.Type;

export const EncounterId = Schema.Int.pipe(Schema.brand("EncounterId"));

export type EncounterId = typeof EncounterId.Type;

export const EnrollmentConfigId = Schema.Int.pipe(
  Schema.brand("EnrollmentConfigId")
);

export type EnrollmentConfigId = typeof EnrollmentConfigId.Type;

export const EventBanId = Schema.Int.pipe(Schema.brand("EventBanId"));

export type EventBanId = typeof EventBanId.Type;

export const EventId = Schema.Int.pipe(Schema.brand("EventId"));

export type EventId = typeof EventId.Type;

export const FacilitatorId = Schema.Int.pipe(Schema.brand("FacilitatorId"));

export type FacilitatorId = typeof FacilitatorId.Type;

export const ParticipationId = Schema.Int.pipe(Schema.brand("ParticipationId"));

export type ParticipationId = typeof ParticipationId.Type;

export const PartyId = Schema.Int.pipe(Schema.brand("PartyId"));

export type PartyId = typeof PartyId.Type;

export const PartyMembershipId = Schema.Int.pipe(
  Schema.brand("PartyMembershipId")
);

export type PartyMembershipId = typeof PartyMembershipId.Type;

export const PersonalDataFieldId = Schema.Int.pipe(
  Schema.brand("PersonalDataFieldId")
);

export type PersonalDataFieldId = typeof PersonalDataFieldId.Type;

export const ProposalCategoryId = Schema.Int.pipe(
  Schema.brand("ProposalCategoryId")
);

export type ProposalCategoryId = typeof ProposalCategoryId.Type;

export const ScheduleChangeLogId = Schema.Int.pipe(
  Schema.brand("ScheduleChangeLogId")
);

export type ScheduleChangeLogId = typeof ScheduleChangeLogId.Type;

export const SessionFieldId = Schema.Int.pipe(Schema.brand("SessionFieldId"));

export type SessionFieldId = typeof SessionFieldId.Type;

export const SessionId = Schema.Int.pipe(Schema.brand("SessionId"));

export type SessionId = typeof SessionId.Type;

export const SpaceId = Schema.Int.pipe(Schema.brand("SpaceId"));

export type SpaceId = typeof SpaceId.Type;

export const TimeSlotId = Schema.Int.pipe(Schema.brand("TimeSlotId"));

export type TimeSlotId = typeof TimeSlotId.Type;

export const TrackId = Schema.Int.pipe(Schema.brand("TrackId"));

export type TrackId = typeof TrackId.Type;

export const UserId = Schema.Int.pipe(Schema.brand("UserId"));

export type UserId = typeof UserId.Type;
