import { Schema } from "effect";
import { defineMessageUnion } from "foldkit/message";

import { PanelFailure } from "../failure.js";

export const FacilitatorListMessage = defineMessageUnion({
  ChangedFilter: { name: Schema.String, value: Schema.String },
  SubmittedFilters: {},
  ToggledAll: { checked: Schema.Boolean },
  ToggledRow: { checked: Schema.Boolean, slug: Schema.String },
});

export type FacilitatorListMessage = typeof FacilitatorListMessage.Type;

export const FacilitatorFormMessage = defineMessageUnion({
  ChangedAccreditation: { value: Schema.String },
  ChangedComment: { value: Schema.String },
  ChangedDisplayName: { value: Schema.String },
  FailedSaveFacilitator: { failure: PanelFailure },
  SubmittedFacilitatorForm: {},
  SucceededSaveFacilitator: { slug: Schema.String },
  ToggledAssignMe: { checked: Schema.Boolean },
  ToggledCollective: { checked: Schema.Boolean },
});

export type FacilitatorFormMessage = typeof FacilitatorFormMessage.Type;
