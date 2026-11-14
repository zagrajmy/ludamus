import { Effect, Schema } from "effect";
import { Command } from "foldkit";

import { catchPanelFailure, FlashNote } from "../panel/failure.js";
import { navigateWithFlash } from "../panel/navigate.js";
import { Backend } from "../rpc.js";
import { ProposalAcceptMessage } from "./message.js";

export const AcceptProposal = Command.define("AcceptProposal", {
  args: {
    eventSlug: Schema.String,
    proposalId: Schema.Int,
    spaceId: Schema.Int,
    timeSlotId: Schema.Int,
  },
  execute: (acceptance) =>
    catchPanelFailure(
      Effect.gen(function* acceptProposal() {
        yield* (yield* Backend).acceptProposal(acceptance);

        return ProposalAcceptMessage.SucceededAccept();
      }).pipe(Effect.provide(Backend.layer)),
      (failure) => ProposalAcceptMessage.FailedAccept({ failure })
    ),
  messages: [
    ProposalAcceptMessage.SucceededAccept,
    ProposalAcceptMessage.FailedAccept,
  ],
});

export const LeaveAccept = Command.define("LeaveAccept", {
  args: { href: Schema.String, notes: Schema.Array(FlashNote) },
  execute: ({ href, notes }) =>
    navigateWithFlash(href, notes).pipe(
      Effect.as(ProposalAcceptMessage.LeftAccept())
    ),
  messages: [ProposalAcceptMessage.LeftAccept],
});
