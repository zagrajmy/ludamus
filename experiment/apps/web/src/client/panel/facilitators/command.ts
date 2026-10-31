import { Effect, Option, Schema } from "effect";
import { Command } from "foldkit";

import { Backend } from "../../rpc.js";
import { catchPanelFailure } from "../failure.js";
import { FacilitatorFormMessage } from "./message.js";

export const SaveFacilitator = Command.define("SaveFacilitator", {
  args: {
    accreditationType: Schema.String,
    assignMe: Schema.Boolean,
    displayName: Schema.String,
    eventSlug: Schema.String,
    facilitatorSlug: Schema.Option(Schema.String),
    internalComment: Schema.String,
    isCollective: Schema.Boolean,
  },
  execute: ({ facilitatorSlug, ...form }) =>
    catchPanelFailure(
      Effect.gen(function* saveFacilitator() {
        const backend = yield* Backend;

        const saved = yield* Option.match(facilitatorSlug, {
          onNone: () => backend.createFacilitator({
                accreditationType: form.accreditationType,
                assignMe: form.assignMe,
                displayName: form.displayName,
                eventSlug: form.eventSlug,
                isCollective: form.isCollective,
              }),
          onSome: (slug) => backend.updateFacilitator({
                accreditationType: form.accreditationType,
                eventSlug: form.eventSlug,
                facilitatorSlug: slug,
                internalComment: form.internalComment,
                isCollective: form.isCollective,
              }),
        });

        return FacilitatorFormMessage.SucceededSaveFacilitator({
          slug: saved.slug,
        });
      }).pipe(Effect.provide(Backend.layer)),
      (failure) => FacilitatorFormMessage.FailedSaveFacilitator({ failure })
    ),
  messages: [
    FacilitatorFormMessage.SucceededSaveFacilitator,
    FacilitatorFormMessage.FailedSaveFacilitator,
  ],
});
