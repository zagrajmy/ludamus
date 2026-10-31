import { Schema } from "effect";
import { File } from "foldkit/file";
import { defineMessageUnion } from "foldkit/message";

import { PanelFailure } from "../failure.js";

export const ProposalListMessage = defineMessageUnion({
  ChangedFilter: { name: Schema.String, value: Schema.String },
  ChangedTrack: { value: Schema.String },
  SubmittedFilters: {},
});

export type ProposalListMessage = typeof ProposalListMessage.Type;

export const ProposalDetailMessage = defineMessageUnion({
  ClosedMenu: { refocus: Schema.Boolean },
  CompletedFocus: {},
  OpenedMenu: { focusFirst: Schema.Boolean },
});

export type ProposalDetailMessage = typeof ProposalDetailMessage.Type;

export const ChosenFile = Schema.Struct({
  dataUrl: Schema.String,
  name: Schema.String,
  size: Schema.Number,
  type: Schema.String,
});

export type ChosenFile = typeof ChosenFile.Type;

export const ProposalFormMessage = defineMessageUnion({
  ChangedFacilitatorSearch: { value: Schema.String },
  ChangedText: { name: Schema.String, value: Schema.String },
  ChosenCover: { cover: ChosenFile },
  ClearedCover: {},
  FailedReadCover: {},
  FailedSaveProposal: { failure: PanelFailure },
  PickedCover: { files: Schema.Array(File) },
  SubmittedProposalForm: {},
  SucceededSaveProposal: { id: Schema.Int },
  ToggledFacilitator: { checked: Schema.Boolean, id: Schema.Int },
  ToggledTrack: { checked: Schema.Boolean, id: Schema.Int },
});

export type ProposalFormMessage = typeof ProposalFormMessage.Type;
