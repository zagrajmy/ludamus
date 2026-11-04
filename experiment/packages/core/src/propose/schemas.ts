import { Schema } from "effect";

import { FieldValue } from "../fields.js";
import {
  EventId,
  ProposalCategoryId,
  SessionId,
  TimeSlotId,
  TrackId,
} from "../ids.js";
import { FieldAnswer, FieldRequirement } from "../proposal/fields.js";
import { ProposeStep } from "../proposal/wizard.js";

export const ProposalFormData = Schema.Record(
  Schema.String,
  Schema.Array(Schema.String)
);

export type ProposalFormData = typeof ProposalFormData.Type;

export const Answers = Schema.Record(Schema.String, FieldAnswer);

export type Answers = typeof Answers.Type;

export const ReusableSessionRecord = Schema.Struct({
  description: Schema.String,
  duration: Schema.String,
  eventName: Schema.String,
  minAge: Schema.Int,
  participantsLimit: Schema.Int,
  presented: Schema.Boolean,
  privateAnswers: Schema.Record(Schema.String, FieldValue),
  publicAnswers: Schema.Record(Schema.String, FieldValue),
  sessionId: SessionId,
  title: Schema.String,
});

export type ReusableSessionRecord = typeof ReusableSessionRecord.Type;

export const ProposalTimeSlot = Schema.Struct({
  endTime: Schema.DateTimeUtc,
  id: TimeSlotId,
  isRequired: Schema.Boolean,
  startTime: Schema.DateTimeUtc,
});

export type ProposalTimeSlot = typeof ProposalTimeSlot.Type;

export const ProposeWizardCategory = Schema.Struct({
  description: Schema.String,
  durations: Schema.Array(Schema.String),
  id: ProposalCategoryId,
  maxParticipantsLimit: Schema.Int,
  minParticipantsLimit: Schema.Int,
  name: Schema.String,
  sessionFields: Schema.Array(FieldRequirement),
  steps: Schema.Array(ProposeStep),
  timeSlots: Schema.Array(ProposalTimeSlot),
});

export type ProposeWizardCategory = typeof ProposeWizardCategory.Type;

export const ReusableFormValues = Schema.Struct({
  categoryId: Schema.NullOr(ProposalCategoryId),
  values: Answers,
});

export const ReusableSession = Schema.Struct({
  eventName: Schema.String,
  formValues: Schema.Array(ReusableFormValues),
  sessionId: SessionId,
  title: Schema.String,
});

export type ReusableSession = typeof ReusableSession.Type;

export const ProposalTrack = Schema.Struct({
  id: TrackId,
  name: Schema.String,
});

export type ProposalTrack = typeof ProposalTrack.Type;

export const ProposerAccount = Schema.Struct({
  answersEverything: Schema.Boolean,
  email: Schema.String,
  name: Schema.String,
  personalAnswers: Schema.Record(Schema.String, Schema.String),
  signedIn: Schema.Boolean,
});

export type ProposerAccount = typeof ProposerAccount.Type;

export const ProposeWizard = Schema.Struct({
  account: ProposerAccount,
  categories: Schema.Array(ProposeWizardCategory),
  event: Schema.Struct({
    id: EventId,
    name: Schema.String,
    slug: Schema.String,
  }),
  personalFields: Schema.Array(FieldRequirement),
  personalFormValues: Answers,
  proposalDescription: Schema.String,
  reusableSessions: Schema.Array(ReusableSession),
  tracks: Schema.Array(ProposalTrack),
  uncategorizedSteps: Schema.Array(ProposeStep),
});

export type ProposeWizard = typeof ProposeWizard.Type;

export const ReadProposalFormInput = Schema.Struct({
  eventSlug: Schema.String,
});

export const CheckableStep = Schema.Literals([
  "personal",
  "category",
  "timeslots",
  "details",
]);

export type CheckableStep = typeof CheckableStep.Type;

export const CheckProposalStepInput = Schema.Struct({
  categoryId: Schema.NullOr(Schema.Int),
  data: ProposalFormData,
  eventSlug: Schema.String,
  step: CheckableStep,
});

export type CheckProposalStepInput = typeof CheckProposalStepInput.Type;

export const DetailsAnswers = Schema.Struct({
  answers: Answers,
  description: Schema.String,
  duration: Schema.String,
  facilitatorName: Schema.String,
  minAge: Schema.Int,
  participantsLimit: Schema.Int,
  title: Schema.String,
});

export type DetailsAnswers = typeof DetailsAnswers.Type;

export const PersonalAnswers = Schema.Struct({
  answers: Answers,
  contactEmail: Schema.String,
});

export type PersonalAnswers = typeof PersonalAnswers.Type;

export const CategoryAccepted = Schema.TaggedStruct("CategoryAccepted", {
  categoryId: ProposalCategoryId,
});

export const PersonalAccepted = Schema.TaggedStruct("PersonalAccepted", {
  formValues: Answers,
  personal: PersonalAnswers,
});

export const TimeSlotsAccepted = Schema.TaggedStruct("TimeSlotsAccepted", {
  timeSlotIds: Schema.Array(TimeSlotId),
});

export const DetailsAccepted = Schema.TaggedStruct("DetailsAccepted", {
  details: DetailsAnswers,
  formValues: Answers,
  trackIds: Schema.Array(TrackId),
});

export const AcceptedStep = Schema.Union([
  CategoryAccepted,
  PersonalAccepted,
  TimeSlotsAccepted,
  DetailsAccepted,
]).pipe(Schema.toTaggedUnion("_tag"));

export type AcceptedStep = typeof AcceptedStep.Type;

export const SubmitProposalInput = Schema.Struct({
  categoryId: Schema.NullOr(Schema.Int),
  details: ProposalFormData,
  eventSlug: Schema.String,
  personal: Schema.NullOr(ProposalFormData),
  timeSlotIds: Schema.Array(Schema.Int),
});

export type SubmitProposalInput = typeof SubmitProposalInput.Type;

export const SubmittedProposal = Schema.Struct({
  sessionId: SessionId,
  slug: Schema.String,
  title: Schema.String,
});

export type SubmittedProposal = typeof SubmittedProposal.Type;
