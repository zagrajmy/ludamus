import type { Update } from "foldkit";
import { modifyFields } from "foldkit/struct";

import { SubmitEnrollPage } from "./command.js";
import { EnrollPageMessage } from "./message.js";
import type { EnrollPageModel } from "./model.js";

type Return = Update.Return<EnrollPageModel, EnrollPageMessage>;

const choicesOf = (model: EnrollPageModel) =>
  model.form.rows
    .filter((row) => !row.disabled)
    .map((row) => ({
      userId: row.userId,
      value: model.included.includes(row.userId) ? "include" : "",
    }));

const guestsOf = (model: EnrollPageModel): number | null => {
  if (model.form.guests === null || model.guests.trim() === "") {
    return null;
  }

  const value = Number(model.guests);

  return Number.isInteger(value) ? value : -1;
};

export const updateEnrollPage = (
  model: EnrollPageModel,
  message: EnrollPageMessage
): Return =>
  EnrollPageMessage.match<Return>(message, {
    ChangedGuests: ({ value }) => ({
      model: modifyFields(model, { guests: () => value }),
    }),
    LeftEnrollPage: () => ({ model }),
    SubmittedEnrollments: () =>
      model.submitting
        ? { model }
        : {
            commands: [
              SubmitEnrollPage({
                eventSlug: model.form.eventSlug,
                input: {
                  choices: choicesOf(model),
                  guests: guestsOf(model),
                  mode: "desired",
                  party: model.partyParam,
                  sessionId: model.form.sessionId,
                },
                locale: model.locale,
              }),
            ],
            model: modifyFields(model, { submitting: () => true }),
          },
    ToggledPerson: ({ userId }) => {
      const row = model.form.rows.find(
        (candidate) => candidate.userId === userId
      );

      if (row === undefined || row.disabled) {
        return { model };
      }

      return {
        model: modifyFields(model, {
          included: (included) =>
            included.includes(userId)
              ? included.filter((id) => id !== userId)
              : [...included, userId],
        }),
      };
    },
  });
