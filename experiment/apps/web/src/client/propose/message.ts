import {
  AcceptedStep,
  CheckableStep,
  FormErrors,
  ProposeStep,
} from "@zagrajmy/core/contracts";
import { Schema } from "effect";
import { defineMessageUnion } from "foldkit/message";

import { PostedForm } from "./model.js";

export const CopyIntent = Schema.TaggedStruct("Copy", {
  sessionId: Schema.Int,
});

export const UndoIntent = Schema.TaggedStruct("Undo", {});

export const SnapshotIntent = Schema.Union([CopyIntent, UndoIntent]).pipe(
  Schema.toTaggedUnion("_tag")
);

export type SnapshotIntent = typeof SnapshotIntent.Type;

export const SubmitRefusal = Schema.Literals([
  "Invalid",
  "Throttled",
  "ClosedOpenEvent",
  "ClosedHiddenEvent",
  "NotFound",
  "SignIn",
  "CategoryRequired",
  "Unknown",
]);

export type SubmitRefusal = typeof SubmitRefusal.Type;

export const ProposeMessage = defineMessageUnion({
  AcceptedStep: {
    accepted: AcceptedStep,
    data: PostedForm,
    descriptionHtml: Schema.String,
    step: CheckableStep,
  },
  ChangedDraftText: { name: Schema.String, value: Schema.String },
  ClickedBack: { from: ProposeStep },
  ClickedCopyFrom: { sessionId: Schema.Int },
  ClickedSubmitProposal: {},
  ClickedUndoCopy: {},
  CompletedNavigation: {},
  EnhancedWriteIn: { name: Schema.String },
  FailedEnhanceWriteIn: { name: Schema.String },
  FailedRequest: {},
  FailedSubmitProposal: {
    errors: FormErrors,
    reason: SubmitRefusal,
    step: Schema.NullOr(ProposeStep),
  },
  ReadForm: { data: PostedForm, intent: SnapshotIntent },
  RejectedStep: { errors: FormErrors },
  SubmittedStep: { step: CheckableStep },
  ToggledCopyMenu: { isOpen: Schema.Boolean },
});

export type ProposeMessage = typeof ProposeMessage.Type;
