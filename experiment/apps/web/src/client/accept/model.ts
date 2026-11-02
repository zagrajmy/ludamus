import { FormError } from "@zagrajmy/core/contracts";
import { Schema } from "effect";

import { ProposalAcceptFlags } from "./flags.js";

export const ProposalAcceptModel = Schema.Struct({
  ...ProposalAcceptFlags.fields,
  errors: Schema.Array(FormError),
  isSaving: Schema.Boolean,
  slotId: Schema.String,
  spaceId: Schema.String,
});

export type ProposalAcceptModel = typeof ProposalAcceptModel.Type;

const soleId = (choices: readonly Readonly<{ id: number }>[]) =>
  choices.length === 1 && choices[0] !== undefined ? String(choices[0].id) : "";

export const initProposalAccept = (
  flags: ProposalAcceptFlags
): ProposalAcceptModel => ({
  ...flags,
  errors: [],
  isSaving: false,
  slotId: soleId(flags.slots),
  spaceId: soleId(flags.spaces),
});
