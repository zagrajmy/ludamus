import { Effect, Option, Schema } from "effect";
import { Command } from "foldkit";
import { focus } from "foldkit/dom";
import { File, readAsDataUrl } from "foldkit/file";

import { Backend } from "../../rpc.js";
import { catchPanelFailure } from "../failure.js";
import { ProposalDetailMessage, ProposalFormMessage } from "./message.js";

export const MENU_ID = "proposal-actions-menu";

export const FocusFirstMenuItem = Command.define("FocusFirstMenuItem", {
  execute: Effect.sleep("0 millis").pipe(
    Effect.andThen(focus(`#${MENU_ID} button`)),
    Effect.ignore,
    Effect.as(ProposalDetailMessage.CompletedFocus())
  ),
  messages: [ProposalDetailMessage.CompletedFocus],
});

export const FocusMenuButton = Command.define("FocusMenuButton", {
  execute: focus(`[aria-controls="${MENU_ID}"]`).pipe(
    Effect.ignore,
    Effect.as(ProposalDetailMessage.CompletedFocus())
  ),
  messages: [ProposalDetailMessage.CompletedFocus],
});

export const ReadCover = Command.define("ReadCover", {
  args: { file: File },
  execute: ({ file }) =>
    readAsDataUrl(file).pipe(
      Effect.map((dataUrl) =>
        ProposalFormMessage.ChosenCover({
          cover: { dataUrl, name: file.name, size: file.size, type: file.type },
        })
      ),
      Effect.orElseSucceed(() => ProposalFormMessage.FailedReadCover())
    ),
  messages: [
    ProposalFormMessage.ChosenCover,
    ProposalFormMessage.FailedReadCover,
  ],
});

const ProposalPayload = {
  categoryId: Schema.String,
  contactEmail: Schema.String,
  coverImage: Schema.NullOr(
    Schema.Struct({ dataUrl: Schema.String, name: Schema.String })
  ),
  coverImageClear: Schema.Boolean,
  description: Schema.String,
  durationHours: Schema.String,
  durationMinutes: Schema.String,
  eventSlug: Schema.String,
  facilitatorIds: Schema.Array(Schema.Int),
  facilitatorName: Schema.String,
  minAge: Schema.String,
  participantsLimit: Schema.String,
  proposalId: Schema.NullOr(Schema.Int),
  timeSlotIds: Schema.Array(Schema.Int),
  title: Schema.String,
  trackIds: Schema.Array(Schema.Int),
};

export const SaveProposal = Command.define("SaveProposal", {
  args: ProposalPayload,
  execute: (payload) =>
    catchPanelFailure(
      Effect.gen(function* saveProposal() {
        const saved = yield* (yield* Backend).saveProposal(payload);

        return ProposalFormMessage.SucceededSaveProposal({ id: saved.id });
      }).pipe(Effect.provide(Backend.layer)),
      (failure) => ProposalFormMessage.FailedSaveProposal({ failure })
    ),
  messages: [
    ProposalFormMessage.SucceededSaveProposal,
    ProposalFormMessage.FailedSaveProposal,
  ],
});

export const optionalCover = <A>(value: Option.Option<A>) =>
  Option.getOrNull(value);
