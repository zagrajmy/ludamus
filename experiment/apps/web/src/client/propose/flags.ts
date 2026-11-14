import {
  AcceptedStep,
  FormErrors,
  ProposeStep,
  ReusableSession,
} from "@zagrajmy/core/contracts";
import { Schema } from "effect";

import { AvatarPerson } from "../../ui/avatar.js";
import { Locale } from "../../ui/i18n.js";

export const ProposeIcon = Schema.Struct({
  paths: Schema.Array(
    Schema.Struct({
      clipRule: Schema.optionalKey(Schema.Literal("evenodd")),
      d: Schema.String,
      fillRule: Schema.optionalKey(Schema.Literal("evenodd")),
    })
  ),
  variant: Schema.Literals(["micro", "mini", "outline", "solid"]),
});

export type ProposeIcon = typeof ProposeIcon.Type;

export const ChoiceOption = Schema.Struct({
  label: Schema.String,
  value: Schema.String,
});

export type ChoiceOption = typeof ChoiceOption.Type;

export const FieldView = Schema.Struct({
  controlRequired: Schema.Boolean,
  fieldType: Schema.Literals(["text", "select", "checkbox", "discord"]),
  helpHtml: Schema.String,
  icon: Schema.NullOr(ProposeIcon),
  isMultiple: Schema.Boolean,
  isPublic: Schema.Boolean,
  isRequired: Schema.Boolean,
  maxLength: Schema.NullOr(Schema.Int),
  name: Schema.String,
  offersCustom: Schema.Boolean,
  options: Schema.Array(ChoiceOption),
  question: Schema.String,
  slug: Schema.String,
});

export type FieldView = typeof FieldView.Type;

export const SlotView = Schema.Struct({
  id: Schema.Int,
  isRequired: Schema.Boolean,
  label: Schema.String,
});

export type SlotView = typeof SlotView.Type;

export const SlotDay = Schema.Struct({
  label: Schema.String,
  slots: Schema.Array(SlotView),
});

export type SlotDay = typeof SlotDay.Type;

export const CategoryView = Schema.Struct({
  description: Schema.String,
  durations: Schema.Array(ChoiceOption),
  id: Schema.Int,
  maxParticipantsLimit: Schema.Int,
  minParticipantsLimit: Schema.Int,
  name: Schema.String,
  sessionFields: Schema.Array(FieldView),
  slotDays: Schema.Array(SlotDay),
  steps: Schema.Array(ProposeStep),
});

export type CategoryView = typeof CategoryView.Type;

export const ProposeFlags = Schema.Struct({
  account: Schema.Struct({
    answers: Schema.Record(Schema.String, Schema.String),
    email: Schema.String,
    name: Schema.String,
    person: AvatarPerson,
    signedIn: Schema.Boolean,
  }),
  categories: Schema.Array(CategoryView),
  descriptionHtml: Schema.String,
  eventName: Schema.String,
  eventSlug: Schema.String,
  locale: Locale,
  loginUrl: Schema.String,
  personalFields: Schema.Array(FieldView),
  personalFormValues: Schema.Record(Schema.String, Schema.Array(Schema.String)),
  reusableSessions: Schema.Array(ReusableSession),
  tracks: Schema.Array(Schema.Struct({ id: Schema.Int, name: Schema.String })),
  uncategorizedSteps: Schema.Array(ProposeStep),
});

export type ProposeFlags = typeof ProposeFlags.Type;

export const StepAccepted = Schema.TaggedStruct("Accepted", {
  descriptionHtml: Schema.String,
  step: AcceptedStep,
});

export const StepRejected = Schema.TaggedStruct("Rejected", {
  errors: FormErrors,
});

export const StepRedirected = Schema.TaggedStruct("Redirected", {
  location: Schema.String,
});

export const StepResponse = Schema.Union([
  StepAccepted,
  StepRejected,
  StepRedirected,
]).pipe(Schema.toTaggedUnion("_tag"));

export type StepResponse = typeof StepResponse.Type;

export const PROPOSE_CATEGORY_HEADER = "x-propose-category";

export const proposePath = (eventSlug: string) =>
  `/event/${encodeURIComponent(eventSlug)}/session/propose/`;

export const stepPath = (options: {
  readonly eventSlug: string;
  readonly step: string;
}) => `${proposePath(options.eventSlug)}parts/${options.step}`;
