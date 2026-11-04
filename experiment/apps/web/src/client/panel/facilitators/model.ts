import { FormError } from "@zagrajmy/core/contracts";
import { Schema } from "effect";

import {
  FacilitatorBinFlags,
  FacilitatorFormFlags,
  FacilitatorsFlags,
} from "./flags.js";

export const FacilitatorsModel = Schema.Struct({
  ...FacilitatorsFlags.fields,
  selected: Schema.Array(Schema.String),
});

export type FacilitatorsModel = typeof FacilitatorsModel.Type;

export const FacilitatorBinModel = Schema.Struct({
  ...FacilitatorBinFlags.fields,
  selected: Schema.Array(Schema.String),
});

export type FacilitatorBinModel = typeof FacilitatorBinModel.Type;

export const FacilitatorFormModel = Schema.Struct({
  ...FacilitatorFormFlags.fields,
  errors: Schema.Array(FormError),
  isSaving: Schema.Boolean,
});

export type FacilitatorFormModel = typeof FacilitatorFormModel.Type;

export const initFacilitatorForm = (
  flags: FacilitatorFormFlags
): FacilitatorFormModel => ({
  ...flags,
  errors: [],
  isSaving: false,
});

export const facilitatorsQuery = (filters: FacilitatorsFlags["filters"]) => {
  const params = new URLSearchParams();

  if (filters.sort !== "" && filters.sort !== "name") {
    params.set("sort", filters.sort);
  }

  params.set("search", filters.search);
  params.set("accreditation", filters.accreditation);
  params.set("organizer", filters.organizer);

  return params.toString();
};
