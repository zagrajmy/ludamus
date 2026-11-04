import type { Update } from "foldkit";
import { modifyFields } from "foldkit/struct";

import { translator } from "../../ui/i18n.js";
import { BROKEN_SAVE, PanelFailure, refusalText } from "../panel/failure.js";
import { AcceptProposal, LeaveAccept } from "./command.js";
import { ProposalAcceptMessage } from "./message.js";
import type { ProposalAcceptModel } from "./model.js";

type Return = Update.Return<ProposalAcceptModel, ProposalAcceptMessage>;

const choiceError = (model: ProposalAcceptModel) => [
  ...(model.spaceId === ""
    ? [{ field: "space", msgid: "This field is required.", vars: {} }]
    : []),
  ...(model.slotId === ""
    ? [{ field: "time_slot", msgid: "This field is required.", vars: {} }]
    : []),
];

export const updateProposalAccept = (
  model: ProposalAcceptModel,
  message: ProposalAcceptMessage
): Return => {
  const words = translator(model.locale);
  const eventHref = `/event/${model.eventSlug}/`;

  const leave = (
    href: string,
    level: "error" | "success",
    text: string
  ): Return => ({
    commands: [LeaveAccept({ href, notes: [{ level, text }] })],
    model,
  });

  return ProposalAcceptMessage.match<Return>(message, {
    ChangedSlot: ({ value }) => ({
      model: modifyFields(model, { slotId: () => value }),
    }),
    ChangedSpace: ({ value }) => ({
      model: modifyFields(model, { spaceId: () => value }),
    }),
    FailedAccept: ({ failure }) =>
      PanelFailure.match<Return>(failure, {
        Broken: () => ({
          model: modifyFields(model, {
            errors: () => [{ field: "", msgid: BROKEN_SAVE, vars: {} }],
            isSaving: () => false,
          }),
        }),
        Conflict: () => ({
          model: modifyFields(model, { isSaving: () => false }),
        }),
        Invalid: ({ errors }) => ({
          model: modifyFields(model, {
            errors: () => errors,
            isSaving: () => false,
          }),
        }),
        Missing: () => leave("/", "error", words.t("Session not found.")),
        Refused: ({ reason }) =>
          leave(eventHref, "error", refusalText(reason, words)),
        Scheduled: () => ({
          model: modifyFields(model, { isSaving: () => false }),
        }),
      }),
    LeftAccept: () => ({ model }),
    SubmittedAccept: () => {
      const missing = choiceError(model);

      if (model.isSaving) {
        return { model };
      }

      return missing.length > 0
        ? { model: modifyFields(model, { errors: () => missing }) }
        : {
            commands: [
              AcceptProposal({
                eventSlug: model.eventSlug,
                proposalId: model.sessionId,
                spaceId: Number(model.spaceId),
                timeSlotId: Number(model.slotId),
              }),
            ],
            model: modifyFields(model, {
              errors: () => [],
              isSaving: () => true,
            }),
          };
    },
    SucceededAccept: () =>
      leave(
        eventHref,
        "success",
        words
          .t("Proposal '{}' has been accepted and added to the agenda.")
          .replace("{}", model.title)
      ),
  });
};
