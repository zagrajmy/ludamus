import { Schema } from "effect";

import { Locale } from "../../ui/i18n.js";

export const AcceptChoice = Schema.Struct({
  group: Schema.String,
  id: Schema.Int,
  label: Schema.String,
});

export type AcceptChoice = typeof AcceptChoice.Type;

export const ScheduleBlocker = Schema.Literals([
  "none",
  "spaces",
  "time_slots",
]);

export type ScheduleBlocker = typeof ScheduleBlocker.Type;

export const AcceptFact = Schema.Struct({
  label: Schema.String,
  value: Schema.String,
});

export const ProposalAcceptFlags = Schema.Struct({
  blocker: ScheduleBlocker,
  contactEmail: Schema.String,
  descriptionHtml: Schema.String,
  eventName: Schema.String,
  eventSlug: Schema.String,
  facilitatorName: Schema.String,
  facts: Schema.Array(AcceptFact),
  fieldValues: Schema.Array(AcceptFact),
  locale: Locale,
  preferredSlots: Schema.Array(Schema.String),
  sessionId: Schema.Int,
  slots: Schema.Array(AcceptChoice),
  spaces: Schema.Array(AcceptChoice),
  title: Schema.String,
});

export type ProposalAcceptFlags = typeof ProposalAcceptFlags.Type;
