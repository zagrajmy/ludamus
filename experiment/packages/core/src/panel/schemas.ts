import { Schema } from "effect";

import { SessionId, UserId } from "../ids.js";
import { SessionStatus } from "../session.js";

export const PanelRole = Schema.Literals(["manager", "comms"]);

export type PanelRole = typeof PanelRole.Type;

export const PanelStats = Schema.Struct({
  hostsCount: Schema.Int,
  pendingProposals: Schema.Int,
  roomsCount: Schema.Int,
  scheduledSessions: Schema.Int,
  totalProposals: Schema.Int,
});

export type PanelStats = typeof PanelStats.Type;

export const ScheduledSession = Schema.Struct({
  endTime: Schema.DateTimeUtc,
  id: SessionId,
  spaceName: Schema.String,
  startTime: Schema.DateTimeUtc,
  title: Schema.String,
});

export type ScheduledSession = typeof ScheduledSession.Type;

export const SphereManager = Schema.Struct({
  id: UserId,
  name: Schema.String,
});

export type SphereManager = typeof SphereManager.Type;

export const EventSlugInput = { eventSlug: Schema.String };

export const TrackForm = Schema.Struct({
  ...EventSlugInput,
  isPublic: Schema.Boolean,
  managerIds: Schema.Array(Schema.Int),
  name: Schema.String,
  spaceIds: Schema.Array(Schema.Int),
});

export type TrackForm = typeof TrackForm.Type;

export const TrackEditForm = Schema.Struct({
  ...TrackForm.fields,
  trackSlug: Schema.String,
});

export type TrackEditForm = typeof TrackEditForm.Type;

export const TrackRef = Schema.Struct({
  ...EventSlugInput,
  trackSlug: Schema.String,
});

export const SavedSlug = Schema.Struct({ slug: Schema.String });

export const Done = Schema.Struct({});

export const FacilitatorForm = Schema.Struct({
  ...EventSlugInput,
  accreditationType: Schema.String,
  assignMe: Schema.Boolean,
  displayName: Schema.String,
  isCollective: Schema.Boolean,
});

export type FacilitatorForm = typeof FacilitatorForm.Type;

export const FacilitatorEditForm = Schema.Struct({
  ...EventSlugInput,
  accreditationType: Schema.String,
  facilitatorSlug: Schema.String,
  internalComment: Schema.String,
  isCollective: Schema.Boolean,
});

export type FacilitatorEditForm = typeof FacilitatorEditForm.Type;

export const FacilitatorRef = Schema.Struct({
  ...EventSlugInput,
  facilitatorSlug: Schema.String,
});

export const ProposalRef = Schema.Struct({
  ...EventSlugInput,
  proposalId: Schema.Int,
});

export const ProposalStatusChange = Schema.Struct({
  ...ProposalRef.fields,
  status: SessionStatus,
});

export const ProposalAcceptance = Schema.Struct({
  ...ProposalRef.fields,
  spaceId: Schema.NullOr(Schema.Int),
  timeSlotId: Schema.NullOr(Schema.Int),
});

export const AcceptedProposal = Schema.Struct({
  scheduled: Schema.Boolean,
  status: SessionStatus,
});

export const ProposalForm = Schema.Struct({
  ...EventSlugInput,
  categoryId: Schema.String,
  contactEmail: Schema.String,
  coverImage: Schema.NullOr(
    Schema.Struct({ dataUrl: Schema.String, name: Schema.String })
  ),
  coverImageClear: Schema.Boolean,
  description: Schema.String,
  durationHours: Schema.String,
  durationMinutes: Schema.String,
  facilitatorIds: Schema.Array(Schema.Int),
  facilitatorName: Schema.String,
  minAge: Schema.String,
  participantsLimit: Schema.String,
  proposalId: Schema.NullOr(Schema.Int),
  timeSlotIds: Schema.Array(Schema.Int),
  title: Schema.String,
  trackIds: Schema.Array(Schema.Int),
});

export type ProposalForm = typeof ProposalForm.Type;

export const SavedProposal = Schema.Struct({ id: Schema.Int });

export { AccreditationType } from "../facilitator.js";

export { FacilitatorHasSessions } from "./facilitator-has-sessions.js";

export { FormError, FormErrorVars, formError } from "./form-error.js";

export { FormInvalid } from "./form-invalid.js";

export { PanelAccessDenied } from "./panel-access-denied.js";

export { ProposalScheduled } from "./proposal-scheduled.js";

export { PanelRefusalReason } from "./refusal-reason.js";
