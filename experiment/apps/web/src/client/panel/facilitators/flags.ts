import { Schema } from "effect";

export const AccreditationValue = Schema.Literals([
  "none",
  "standard",
  "guest",
  "honorary",
  "creator",
]);

export type AccreditationValue = typeof AccreditationValue.Type;

export const FacilitatorRow = Schema.Struct({
  accreditationType: AccreditationValue,
  displayName: Schema.String,
  isLinked: Schema.Boolean,
  organizerName: Schema.String,
  sessionCount: Schema.Int,
  slug: Schema.String,
});

export type FacilitatorRow = typeof FacilitatorRow.Type;

export const FacilitatorColumn = Schema.Literals([
  "name",
  "linked",
  "guild",
  "sessions",
  "accreditation",
  "organizer",
]);

export type FacilitatorColumn = typeof FacilitatorColumn.Type;

export const FacilitatorFilters = Schema.Struct({
  accreditation: Schema.String,
  organizer: Schema.String,
  search: Schema.String,
  sort: Schema.String,
});

export type FacilitatorFilters = typeof FacilitatorFilters.Type;

export const FacilitatorsFlags = Schema.Struct({
  columns: Schema.Array(FacilitatorColumn),
  eventSlug: Schema.String,
  filters: FacilitatorFilters,
  listPath: Schema.String,
  rows: Schema.Array(FacilitatorRow),
});

export type FacilitatorsFlags = typeof FacilitatorsFlags.Type;

export const BinRow = Schema.Struct({
  deletedLabel: Schema.String,
  displayName: Schema.String,
  slug: Schema.String,
});

export const FacilitatorBinFlags = Schema.Struct({
  eventSlug: Schema.String,
  listPath: Schema.String,
  rows: Schema.Array(BinRow),
});

export type FacilitatorBinFlags = typeof FacilitatorBinFlags.Type;

export const FacilitatorSession = Schema.Struct({
  id: Schema.Int,
  isDeleted: Schema.Boolean,
  isScheduled: Schema.Boolean,
  status: Schema.Literals(["pending", "accepted", "on_hold", "rejected"]),
  title: Schema.String,
});

export const FacilitatorDetailFlags = Schema.Struct({
  accreditationType: AccreditationValue,
  displayName: Schema.String,
  eventSlug: Schema.String,
  internalComment: Schema.String,
  isCollective: Schema.Boolean,
  isDeleted: Schema.Boolean,
  linkedUser: Schema.String,
  organizerName: Schema.String,
  sessions: Schema.Array(FacilitatorSession),
  slug: Schema.String,
});

export type FacilitatorDetailFlags = typeof FacilitatorDetailFlags.Type;

export const FacilitatorFormValues = Schema.Struct({
  accreditationType: Schema.String,
  assignMe: Schema.Boolean,
  displayName: Schema.String,
  internalComment: Schema.String,
  isCollective: Schema.Boolean,
});

export type FacilitatorFormValues = typeof FacilitatorFormValues.Type;

export const FacilitatorFormFlags = Schema.Struct({
  eventSlug: Schema.String,
  facilitatorSlug: Schema.OptionFromOptional(Schema.String),
  organizerName: Schema.String,
  savedName: Schema.String,
  values: FacilitatorFormValues,
});

export type FacilitatorFormFlags = typeof FacilitatorFormFlags.Type;
