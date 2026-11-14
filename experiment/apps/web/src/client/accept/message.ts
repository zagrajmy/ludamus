import { Schema } from "effect";
import { defineMessageUnion } from "foldkit/message";

import { PanelFailure } from "../panel/failure.js";

export const ProposalAcceptMessage = defineMessageUnion({
  ChangedSlot: { value: Schema.String },
  ChangedSpace: { value: Schema.String },
  FailedAccept: { failure: PanelFailure },
  LeftAccept: {},
  SubmittedAccept: {},
  SucceededAccept: {},
});

export type ProposalAcceptMessage = typeof ProposalAcceptMessage.Type;

export { ProposalAcceptMessage as Message };
