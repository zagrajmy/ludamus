import { Schema } from "effect";

import { NamedId, SessionStatusSchema } from "../schemas.js";

export const ProposalRow = Schema.Struct({
  categoryName: Schema.String,
  createdLabel: Schema.String,
  facilitatorName: Schema.String,
  id: Schema.Int,
  isScheduled: Schema.Boolean,
  status: SessionStatusSchema,
  title: Schema.String,
});

export type ProposalRow = typeof ProposalRow.Type;

export const ProposalColumn = Schema.Struct({
  key: Schema.String,
  kind: Schema.Literals(["text", "status", "created"]),
  label: Schema.String,
});

export type ProposalColumn = typeof ProposalColumn.Type;

export const FilterField = Schema.Struct({
  id: Schema.Int,
  name: Schema.String,
  options: Schema.Array(
    Schema.Struct({ label: Schema.String, value: Schema.String })
  ),
  value: Schema.String,
});

export type FilterField = typeof FilterField.Type;

export const TrackChoice = Schema.Struct({
  id: Schema.Int,
  isManaged: Schema.Boolean,
  name: Schema.String,
});

export const ProposalFilters = Schema.Struct({
  category: Schema.String,
  search: Schema.String,
  sort: Schema.String,
  status: Schema.String,
  track: Schema.String,
});

export type ProposalFilters = typeof ProposalFilters.Type;

export const ProposalsFlags = Schema.Struct({
  categories: Schema.Array(NamedId),
  cells: Schema.Array(
    Schema.Struct({
      id: Schema.Int,
      values: Schema.Record(Schema.String, Schema.String),
    })
  ),
  columns: Schema.Array(ProposalColumn),
  deleted: Schema.Array(ProposalRow),
  eventSlug: Schema.String,
  fields: Schema.Array(FilterField),
  filterStatus: Schema.String,
  filters: ProposalFilters,
  fullPath: Schema.String,
  hasProposals: Schema.Boolean,
  listPath: Schema.String,
  rows: Schema.Array(ProposalRow),
  tracks: Schema.Array(TrackChoice),
});

export type ProposalsFlags = typeof ProposalsFlags.Type;

export const DetailFact = Schema.Struct({
  term: Schema.String,
  value: Schema.String,
});

export const ProposalDetailFlags = Schema.Struct({
  backUrl: Schema.String,
  categoryName: Schema.String,
  contactEmail: Schema.String,
  coverUrl: Schema.String,
  createdLabel: Schema.String,
  description: Schema.String,
  durationLabel: Schema.String,
  eventSlug: Schema.String,
  facilitatorName: Schema.String,
  facilitators: Schema.Array(
    Schema.Struct({ name: Schema.String, slug: Schema.String })
  ),
  fieldValues: Schema.Array(DetailFact),
  id: Schema.Int,
  minAge: Schema.Int,
  modifiedLabel: Schema.String,
  participantsLimit: Schema.Int,
  preferredSlots: Schema.Array(Schema.String),
  presenter: Schema.String,
  scheduled: Schema.String,
  slug: Schema.String,
  status: SessionStatusSchema,
  title: Schema.String,
  tracks: Schema.Array(
    Schema.Struct({ name: Schema.String, slug: Schema.String })
  ),
});

export type ProposalDetailFlags = typeof ProposalDetailFlags.Type;

export const ProposalFormValues = Schema.Struct({
  categoryId: Schema.String,
  contactEmail: Schema.String,
  description: Schema.String,
  durationHours: Schema.String,
  durationMinutes: Schema.String,
  facilitatorIds: Schema.Array(Schema.Int),
  facilitatorName: Schema.String,
  minAge: Schema.String,
  participantsLimit: Schema.String,
  timeSlotIds: Schema.Array(Schema.Int),
  title: Schema.String,
  trackIds: Schema.Array(Schema.Int),
});

export type ProposalFormValues = typeof ProposalFormValues.Type;

export const ProposalFormFlags = Schema.Struct({
  cancelUrl: Schema.String,
  categories: Schema.Array(NamedId),
  coverName: Schema.String,
  coverUrl: Schema.String,
  eventSlug: Schema.String,
  facilitators: Schema.Array(NamedId),
  next: Schema.String,
  proposalId: Schema.OptionFromOptional(Schema.Int),
  savedTitle: Schema.String,
  tracks: Schema.Array(NamedId),
  values: ProposalFormValues,
});

export type ProposalFormFlags = typeof ProposalFormFlags.Type;
