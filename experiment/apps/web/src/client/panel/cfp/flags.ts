import { Schema } from "effect";

export const CategoryWindow = Schema.Literals([
  "not_set",
  "closed",
  "upcoming",
  "active",
]);

export type CategoryWindow = typeof CategoryWindow.Type;

export const CategoryRow = Schema.Struct({
  acceptedCount: Schema.Int,
  hasProposals: Schema.Boolean,
  name: Schema.String,
  proposalsCount: Schema.Int,
  slug: Schema.String,
  window: CategoryWindow,
  windowLabel: Schema.String,
});

export type CategoryRow = typeof CategoryRow.Type;

export const CfpFlags = Schema.Struct({
  categories: Schema.Array(CategoryRow),
  eventSlug: Schema.String,
});

export type CfpFlags = typeof CfpFlags.Type;
