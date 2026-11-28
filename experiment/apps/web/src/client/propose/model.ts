import {
  DetailsAnswers,
  FormErrors,
  PersonalAnswers,
  ProposeStep,
} from "@zagrajmy/core/contracts";
import { Schema } from "effect";

import { ProposeFlags } from "./flags.js";
import type { CategoryView } from "./flags.js";

export const PostedForm = Schema.Record(
  Schema.String,
  Schema.Array(Schema.String)
);

export type PostedForm = typeof PostedForm.Type;

export const AcceptedDetails = Schema.Struct({
  details: DetailsAnswers,
  trackIds: Schema.Array(Schema.Int),
});

export const ProposeModel = Schema.Struct({
  acceptedDetails: Schema.NullOr(AcceptedDetails),
  acceptedPersonal: Schema.NullOr(PersonalAnswers),
  categoryId: Schema.NullOr(Schema.Int),
  copiedSnapshot: Schema.NullOr(PostedForm),
  descriptionHtml: Schema.String,
  details: Schema.NullOr(PostedForm),
  detailsDraft: PostedForm,
  enhancedWriteIns: Schema.Array(Schema.String),
  errors: FormErrors,
  flags: ProposeFlags,
  formRevision: Schema.Int,
  isBusy: Schema.Boolean,
  isCopyMenuOpen: Schema.Boolean,
  personal: Schema.NullOr(PostedForm),
  personalDraft: PostedForm,
  requestFailed: Schema.Boolean,
  step: ProposeStep,
  timeSlotIds: Schema.Array(Schema.Int),
});

export type ProposeModel = typeof ProposeModel.Type;

export const categoryOf = (model: {
  readonly flags: ProposeFlags;
  readonly categoryId: number | null;
}): CategoryView | null =>
  model.flags.categories.find((category) => category.id === model.categoryId) ??
  null;

export const stepsOf = (model: {
  readonly flags: ProposeFlags;
  readonly categoryId: number | null;
}): readonly ProposeStep[] =>
  categoryOf(model)?.steps ?? model.flags.uncategorizedSteps;

export const initialDetailsDraft = (flags: ProposeFlags): PostedForm => ({
  facilitator_name: [flags.account.name],
  min_age: ["0"],
});

export const initPropose = (flags: ProposeFlags): ProposeModel => {
  const categoryId =
    flags.categories.length === 1 ? (flags.categories[0]?.id ?? null) : null;

  const steps = stepsOf({ categoryId, flags });

  return {
    acceptedDetails: null,
    acceptedPersonal: steps.includes("personal")
      ? null
      : { answers: flags.account.answers, contactEmail: flags.account.email },
    categoryId,
    copiedSnapshot: null,
    descriptionHtml: "",
    details: null,
    detailsDraft: initialDetailsDraft(flags),
    enhancedWriteIns: [],
    errors: {},
    flags,
    formRevision: 0,
    isBusy: false,
    isCopyMenuOpen: false,
    personal: null,
    personalDraft: {
      ...flags.personalFormValues,
      contact_email: [flags.account.email],
    },
    requestFailed: false,
    step: steps[0] ?? "review",
    timeSlotIds: [],
  };
};
