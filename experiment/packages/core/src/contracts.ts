import { defineContract } from "@zagrajmy/capability/contract";
import { Schema } from "effect";

import { EventSummary } from "./event.js";
import { InvalidStoreInput, StoreError } from "./ports/store-error.js";

export const StoreFailureSchema = Schema.Union([StoreError, InvalidStoreInput]);

export const listEventsContract = defineContract("listEvents", {
  annotations: { idempotent: true, readOnly: true },
  description: "Published events of the current sphere, soonest first",
  failure: StoreFailureSchema,
  input: Schema.Struct({}),
  output: Schema.Array(EventSummary),
});

export { AgendaItem } from "./agenda-item.js";

export { Announcement } from "./announcement.js";

export { BookmarkCount, BookmarkState } from "./bookmark.js";

export {
  ContentFieldChange,
  FacilitatorChangeLogEntry,
  ScheduleChangeAction,
  ScheduleChangeLogEntry,
} from "./change-log.js";

export { Encounter } from "./encounter.js";

export { EnrollmentConfig, EnrollmentWindow } from "./enrollment-config.js";

export {
  Event,
  EventListItem,
  EventProposalSettings,
  EventSummary,
  EventVisibility,
} from "./event.js";

export {
  AccreditationType,
  Facilitator,
  FacilitatorListItem,
  FacilitatorSessionCounts,
} from "./facilitator.js";

export {
  FieldOption,
  FieldValue,
  PersonalDataAnswer,
  PersonalDataField,
  PersonalFieldType,
  SessionField,
  SessionFieldAnswer,
  SessionFieldRequirement,
  SessionFieldType,
} from "./fields.js";

export {
  AgendaItemId,
  AnnouncementId,
  EncounterId,
  EnrollmentConfigId,
  EventBanId,
  EventId,
  FacilitatorId,
  ParticipationId,
  PartyId,
  PartyMembershipId,
  PersonalDataFieldId,
  ProposalCategoryId,
  ScheduleChangeLogId,
  SessionFieldId,
  SessionId,
  SpaceId,
  TimeSlotId,
  TrackId,
  UserId,
} from "./ids.js";

export {
  ParticipationStatus,
  SessionSeat,
  SessionSeats,
} from "./participation.js";

export {
  Party,
  PartyByToken,
  PartyConsentMode,
  PartyInvite,
  PartyMember,
  PartyMembershipStatus,
} from "./party.js";

export {
  DuplicateName,
  InvalidStoreInput,
  NotFound,
  StoreError,
} from "./ports/store-error.js";

export {
  CategoryRequirements,
  CategoryStats,
  PromotionMode,
  ProposalCategory,
  TimeSlotRequirement,
} from "./proposal-category.js";

export { EventBan, ShadowbanWarning } from "./safety.js";

export {
  Session,
  SessionCard,
  SessionListItem,
  SessionStatus,
} from "./session.js";

export { Location, Space, SpaceOption } from "./space.js";

export { Sphere, SphereId } from "./sphere.js";

export { TimeSlot } from "./time-slot.js";

export { Track, TrackListItem, TrackSessionCounts } from "./track.js";

export { AgeBand, User, UserSummary, UserType } from "./user.js";

export const contracts = [listEventsContract] as const;

export {
  ClaimResult,
  EnrollmentAccess,
  EnrollmentWindowData,
  Offer,
} from "./enrollment/schemas.js";
export {
  EnrollRequestChoice,
  EnrollmentBatch,
  EnrollmentRequest,
  SkipReason,
} from "./enrollment/enroll.js";
export {
  FieldAnswer,
  FieldControl,
  FieldControls,
  FieldRequirement,
  FieldValidation,
  OrganizerField,
  OrganizerFieldOption,
} from "./proposal/fields.js";
export {
  CivilDate,
  DayOfWindows,
  LocalDateTime,
  LocalWindow,
} from "./timeslots/day-turnover.js";
