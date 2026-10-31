import { defineContract } from "@zagrajmy/capability/contract";
import { Schema } from "effect";

import { EventPage, ReadEventPageInput, ReadEventSessionInput } from "./event-page/event-page.js";
import {
  BookmarkInput,
  BookmarkToggled,
  EnrollmentForm,
  EnrollmentRefused,
  ExpiredOffers,
  LoginRequired,
  OfferResolution,
  OfferTokenInput,
  OfferView,
  ReadEnrollFooterInput,
  ReadEnrollmentFormInput,
  SessionFooter,
  SubmitEnrollmentsInput,
  SubmittedEnrollments,
} from "./enrollment/api.js";
import { EnrollmentStoreError } from "./enrollment/errors.js";
import { EventSummary } from "./event.js";
import {
  Done,
  FacilitatorEditForm,
  FacilitatorForm,
  FacilitatorHasSessions,
  FacilitatorRef,
  FormInvalid,
  PanelAccessDenied,
  ProposalForm,
  ProposalRef,
  ProposalScheduled,
  ProposalStatusChange,
  SavedProposal,
  SavedSlug,
  TrackEditForm,
  TrackForm,
  TrackRef,
} from "./panel/schemas.js";
import {
  InvalidStoreInput,
  NotFound,
  StoreError,
} from "./ports/store-error.js";
import { AnonymousProposalsDisabled } from "./propose/anonymous-proposals-disabled.js";
import { CategoryRequired } from "./propose/category-required.js";
import { ProposalInvalid } from "./propose/proposal-invalid.js";
import { ProposalsClosed } from "./propose/proposals-closed.js";
import {
  AcceptedStep,
  CheckProposalStepInput,
  ProposeWizard,
  ReadProposalFormInput,
  SubmitProposalInput,
  SubmittedProposal,
} from "./propose/schemas.js";
import { SubmissionThrottled } from "./propose/submission-throttled.js";
import { SessionCard } from "./session.js";

export const StoreFailureSchema = Schema.Union([StoreError, InvalidStoreInput]);

export const listEventsContract = defineContract("listEvents", {
  annotations: { idempotent: true, readOnly: true },
  description: "Published events of the current sphere, soonest first",
  failure: StoreFailureSchema,
  input: Schema.Struct({}),
  output: Schema.Array(EventSummary),
});

export const readEventPageContract = defineContract("readEventPage", {
  annotations: { idempotent: true, readOnly: true },
  description:
    "An open event of the current sphere with its public schedule, filterable fields and enrollment windows",
  failure: Schema.Union([NotFound, StoreError, InvalidStoreInput]),
  input: ReadEventPageInput,
  output: EventPage,
});

export const readEventSessionContract = defineContract("readEventSession", {
  annotations: { idempotent: true, readOnly: true },
  description:
    "One publicly scheduled session of an open event, with its roster",
  failure: Schema.Union([NotFound, StoreError, InvalidStoreInput]),
  input: ReadEventSessionInput,
  output: SessionCard,
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

const PanelRefusals = [NotFound, PanelAccessDenied, StoreError, InvalidStoreInput] as const;

const panelFailure = Schema.Union([...PanelRefusals]);

const panelFormFailure = Schema.Union([...PanelRefusals, FormInvalid]);

export const createTrackContract = defineContract("createTrack", {
  annotations: { readOnly: false },
  description:
    "Create a track in an event the viewer manages, with its spaces and sphere managers",
  failure: panelFormFailure,
  input: TrackForm,
  output: SavedSlug,
});

export const updateTrackContract = defineContract("updateTrack", {
  annotations: { idempotent: true, readOnly: false },
  description: "Rename a track of a managed event and reassign its spaces and managers",
  failure: panelFormFailure,
  input: TrackEditForm,
  output: SavedSlug,
});

export const deleteTrackContract = defineContract("deleteTrack", {
  annotations: { destructive: true, readOnly: false },
  description: "Delete a track of a managed event; its sessions stay",
  failure: panelFailure,
  input: TrackRef,
  output: Done,
});

export const createFacilitatorContract = defineContract("createFacilitator", {
  annotations: { readOnly: false },
  description: "Add a facilitator to an event the viewer manages",
  failure: panelFormFailure,
  input: FacilitatorForm,
  output: SavedSlug,
});

export const updateFacilitatorContract = defineContract("updateFacilitator", {
  annotations: { idempotent: true, readOnly: false },
  description:
    "Change a facilitator's accreditation, internal comment and parallel-run flag; the change is logged",
  failure: panelFormFailure,
  input: FacilitatorEditForm,
  output: SavedSlug,
});

export const deleteFacilitatorContract = defineContract("deleteFacilitator", {
  annotations: { destructive: true, readOnly: false },
  description:
    "Soft-delete a facilitator who is named on no session; refuses with the session counts otherwise",
  failure: Schema.Union([...PanelRefusals, FacilitatorHasSessions]),
  input: FacilitatorRef,
  output: Done,
});

export const restoreFacilitatorContract = defineContract("restoreFacilitator", {
  annotations: { idempotent: false, readOnly: false },
  description: "Bring a soft-deleted facilitator back into the program",
  failure: panelFailure,
  input: FacilitatorRef,
  output: Done,
});

export const changeProposalStatusContract = defineContract("changeProposalStatus", {
  annotations: { idempotent: true, readOnly: false },
  description:
    "Move a proposal of a managed event to pending, accepted, on hold or rejected; a scheduled one can only stay accepted",
  failure: Schema.Union([...PanelRefusals, ProposalScheduled]),
  input: ProposalStatusChange,
  output: Done,
});

export const deleteProposalContract = defineContract("deleteProposal", {
  annotations: { destructive: true, readOnly: false },
  description: "Soft-delete a proposal of a managed event into the proposal bin",
  failure: panelFailure,
  input: ProposalRef,
  output: Done,
});

export const restoreProposalContract = defineContract("restoreProposal", {
  annotations: { readOnly: false },
  description: "Restore a soft-deleted proposal of a managed event",
  failure: panelFailure,
  input: ProposalRef,
  output: Done,
});

export const saveProposalContract = defineContract("saveProposal", {
  annotations: { readOnly: false },
  description:
    "Create (proposalId null) or edit a proposal of a managed event: content, category, facilitators, tracks, time slots and cover image",
  failure: panelFormFailure,
  input: ProposalForm,
  output: SavedProposal,
});

export const panelContracts = [
  createTrackContract,
  updateTrackContract,
  deleteTrackContract,
  createFacilitatorContract,
  updateFacilitatorContract,
  deleteFacilitatorContract,
  restoreFacilitatorContract,
  changeProposalStatusContract,
  deleteProposalContract,
  restoreProposalContract,
  saveProposalContract,
] as const;

const EnrollmentFailures = [
  NotFound,
  EnrollmentRefused,
  LoginRequired,
  EnrollmentStoreError,
  StoreError,
  InvalidStoreInput,
] as const;

export const readEnrollmentFormContract = defineContract(
  "readEnrollmentForm",
  {
    annotations: { idempotent: true, readOnly: true },
    description:
      "Who the signed-in viewer can seat in one session of the current sphere: themselves, their companions and party members, with each person's state",
    failure: Schema.Union([...EnrollmentFailures]),
    input: ReadEnrollmentFormInput,
    output: EnrollmentForm,
  }
);

export const readEnrollFooterContract = defineContract("readEnrollFooter", {
  annotations: { idempotent: true, readOnly: true },
  description:
    "The seat control the session modal offers the signed-in viewer: enroll, join the waiting list, cancel, leave, or when enrollment opens",
  failure: Schema.Union([...EnrollmentFailures]),
  input: ReadEnrollFooterInput,
  output: Schema.Array(SessionFooter),
});

export const submitEnrollmentsContract = defineContract("submitEnrollments", {
  annotations: { readOnly: false },
  description:
    "Enroll, waitlist or cancel the viewer, their companions, party members and guests in one session; a freed seat promotes the waiting list",
  failure: Schema.Union([...EnrollmentFailures]),
  input: SubmitEnrollmentsInput,
  output: SubmittedEnrollments,
});

export const readOfferContract = defineContract("readOffer", {
  annotations: { anonymousSafe: true, idempotent: true, readOnly: true },
  description:
    "A seat offered or held for someone, read by its claim token",
  failure: Schema.Union([...EnrollmentFailures]),
  input: OfferTokenInput,
  output: OfferView,
});

export const claimOfferContract = defineContract("claimOffer", {
  annotations: { anonymousSafe: true, idempotent: true, readOnly: false },
  description:
    "Confirm an offered or held seat with its claim token; the token is the credential",
  failure: Schema.Union([...EnrollmentFailures]),
  input: OfferTokenInput,
  output: OfferResolution,
});

export const declineOfferContract = defineContract("declineOffer", {
  annotations: { anonymousSafe: true, idempotent: true, readOnly: false },
  description:
    "Turn down an offered or held seat with its claim token; the seat goes to the next person waiting",
  failure: Schema.Union([...EnrollmentFailures]),
  input: OfferTokenInput,
  output: OfferResolution,
});

export const expireOffersContract = defineContract("expireOffers", {
  annotations: { anonymousSafe: true, idempotent: true, readOnly: false },
  description:
    "Release every offer in the current sphere whose claim deadline has passed and promote the next people waiting; safe to repeat",
  failure: Schema.Union([...EnrollmentFailures]),
  input: Schema.Struct({}),
  output: ExpiredOffers,
});

export const toggleBookmarkContract = defineContract("toggleBookmark", {
  annotations: { readOnly: false },
  description: "Bookmark or unbookmark a public session for the viewer",
  failure: Schema.Union([...EnrollmentFailures]),
  input: BookmarkInput,
  output: BookmarkToggled,
});

export const enrollmentContracts = [
  readEnrollmentFormContract,
  readEnrollFooterContract,
  submitEnrollmentsContract,
  readOfferContract,
  claimOfferContract,
  declineOfferContract,
  expireOffersContract,
  toggleBookmarkContract,
] as const;

const ProposeRefusals = [
  NotFound,
  ProposalsClosed,
  AnonymousProposalsDisabled,
  StoreError,
  InvalidStoreInput,
] as const;

export const readProposalFormContract = defineContract("readProposalForm", {
  annotations: { idempotent: true, readOnly: true },
  description:
    "What the proposal wizard of an event asks: its categories with their questions, durations and time slots, the proposer's questions, public tracks, and what the viewer's account and earlier sessions already answer",
  failure: Schema.Union([...ProposeRefusals]),
  input: ReadProposalFormInput,
  output: ProposeWizard,
});

export const checkProposalStepContract = defineContract("checkProposalStep", {
  annotations: { idempotent: true, readOnly: true },
  description:
    "Validate one step of the proposal wizard (category, personal details, time slots or session details) as the submit will, returning the cleaned answers or the field errors",
  failure: Schema.Union([...ProposeRefusals, CategoryRequired, ProposalInvalid]),
  input: CheckProposalStepInput,
  output: AcceptedStep,
});

export const submitProposalContract = defineContract("submitProposal", {
  annotations: { anonymousSafe: true, readOnly: false },
  description:
    "Propose a session to an event: validates every step again, finds or creates the proposer's facilitator and creates the session as pending with its answers, time slot preferences and tracks; anonymous proposers are limited per IP",
  failure: Schema.Union([
    ...ProposeRefusals,
    CategoryRequired,
    ProposalInvalid,
    SubmissionThrottled,
  ]),
  input: SubmitProposalInput,
  output: SubmittedProposal,
});

export const proposeContracts = [
  readProposalFormContract,
  checkProposalStepContract,
  submitProposalContract,
] as const;

export const contracts = [
  listEventsContract,
  readEventPageContract,
  readEventSessionContract,
  ...panelContracts,
  ...enrollmentContracts,
  ...proposeContracts,
] as const;

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

export {
  COMPACT_SCHEDULE_MIN_SESSIONS,
  EventPage,
  ReadEventPageInput,
  ReadEventSessionInput,
} from "./event-page/event-page.js";

export {
  FacilitatorHasSessions,
  FormError,
  FormInvalid,
  PanelAccessDenied,
  PanelRefusalReason,
  PanelRole,
  PanelStats,
  ProposalScheduled,
  SphereManager,
} from "./panel/schemas.js";

export {
  EnrollmentForm,
  EnrollmentNotice,
  EnrollmentRefused,
  RefusalDestination,
  EnrollmentRow,
  LoginRequired,
  OfferResolution,
  OfferView,
  SessionFooter,
  SubmitEnrollmentsInput,
  SubmittedEnrollments,
} from "./enrollment/api.js";

export { EnrollActions, EnrollFooter, SeatBadge } from "./enrollment/footer.js";

export { EnrollmentStoreError } from "./enrollment/errors.js";

export {
  AcceptedStep,
  CategoryAccepted,
  CheckableStep,
  CheckProposalStepInput,
  DetailsAccepted,
  DetailsAnswers,
  PersonalAccepted,
  PersonalAnswers,
  ProposeWizard,
  ProposeWizardCategory,
  ProposalFormData,
  ProposalTimeSlot,
  ProposalTrack,
  ProposerAccount,
  ReusableSession,
  SubmitProposalInput,
  SubmittedProposal,
  TimeSlotsAccepted,
} from "./propose/schemas.js";
export { AnonymousProposalsDisabled } from "./propose/anonymous-proposals-disabled.js";
export { CategoryRequired } from "./propose/category-required.js";
export { ProposalInvalid } from "./propose/proposal-invalid.js";
export { ProposalsClosed } from "./propose/proposals-closed.js";
export { SubmissionThrottled } from "./propose/submission-throttled.js";
export { FieldError, FormErrors } from "./proposal/form-fields.js";
export { ProposeStep } from "./proposal/wizard.js";
