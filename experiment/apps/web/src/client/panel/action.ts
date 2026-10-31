import { Schema } from "effect";
import { defineTaggedUnion } from "foldkit/schema";

import { SessionStatusSchema } from "./schemas.js";

export const PanelAction = defineTaggedUnion({
  ChangeProposalStatus: {
    eventSlug: Schema.String,
    next: Schema.String,
    proposalId: Schema.Int,
    status: SessionStatusSchema,
  },
  DeleteFacilitator: {
    eventSlug: Schema.String,
    facilitatorSlug: Schema.String,
    next: Schema.String,
  },
  DeleteProposal: { eventSlug: Schema.String, proposalId: Schema.Int },
  DeleteTrack: { eventSlug: Schema.String, trackSlug: Schema.String },
  RestoreFacilitator: {
    eventSlug: Schema.String,
    facilitatorSlug: Schema.String,
    next: Schema.String,
  },
  RestoreProposal: { eventSlug: Schema.String, proposalId: Schema.Int },
});

export type PanelAction = typeof PanelAction.Type;

export const ConfirmIcon = Schema.Literals([
  "bell-alert",
  "exclamation-triangle",
]);

export const ConfirmPrompt = Schema.Struct({
  confirmLabel: Schema.String,
  icon: ConfirmIcon,
  message: Schema.String,
});

export type ConfirmPrompt = typeof ConfirmPrompt.Type;

export const PendingConfirm = Schema.Struct({
  action: PanelAction,
  prompt: ConfirmPrompt,
});

export type PendingConfirm = typeof PendingConfirm.Type;
