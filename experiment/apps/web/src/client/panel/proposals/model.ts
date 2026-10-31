import { FormError } from "@zagrajmy/core/contracts";
import { Option, Schema } from "effect";

import { ProposalDetailFlags, ProposalFormFlags } from "./flags.js";
import type { ProposalFilters } from "./flags.js";
import { ChosenFile } from "./message.js";

export const ProposalDetailModel = Schema.Struct({
  ...ProposalDetailFlags.fields,
  isMenuOpen: Schema.Boolean,
});

export type ProposalDetailModel = typeof ProposalDetailModel.Type;

export const ProposalFormModel = Schema.Struct({
  ...ProposalFormFlags.fields,
  cover: Schema.Option(ChosenFile),
  coverCleared: Schema.Boolean,
  errors: Schema.Array(FormError),
  facilitatorSearch: Schema.String,
  isSaving: Schema.Boolean,
});

export type ProposalFormModel = typeof ProposalFormModel.Type;

export const initProposalForm = (
  flags: ProposalFormFlags
): ProposalFormModel => ({
  ...flags,
  cover: Option.none(),
  coverCleared: false,
  errors: [],
  facilitatorSearch: "",
  isSaving: false,
});

export const proposalsQuery = (
  filters: ProposalFilters,
  fields: readonly Readonly<{ id: number; value: string }>[]
) => {
  const params = new URLSearchParams();

  params.set("track", filters.track);

  if (filters.sort !== "") {
    params.set("sort", filters.sort);
  }

  params.set("search", filters.search);

  if (filters.category !== "") {
    params.set("category", filters.category);
  }

  params.set("status", filters.status);

  for (const field of fields) {
    params.set(`field_${field.id}`, field.value);
  }

  return params.toString();
};

export const trackFormQuery = (
  options: Readonly<{
    filters: ProposalFilters;
    fields: readonly Readonly<{ id: number; value: string }>[];
    statusValue: string;
    track: string;
  }>
) => {
  const params = new URLSearchParams();

  for (const field of options.fields) {
    params.set(`field_${field.id}`, field.value);
  }

  if (options.filters.search !== "") {
    params.set("search", options.filters.search);
  }

  params.set("status", options.statusValue);

  if (options.filters.category !== "") {
    params.set("category", options.filters.category);
  }

  params.set("track", options.track);

  return params.toString();
};
