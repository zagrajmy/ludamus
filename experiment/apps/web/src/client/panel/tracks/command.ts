import { Effect, Option, Schema } from "effect";
import { Command } from "foldkit";

import { Backend } from "../../rpc.js";
import { catchPanelFailure } from "../failure.js";
import { TrackFormMessage } from "./message.js";

export const SaveTrack = Command.define("SaveTrack", {
  args: {
    eventSlug: Schema.String,
    isPublic: Schema.Boolean,
    managerIds: Schema.Array(Schema.Int),
    name: Schema.String,
    spaceIds: Schema.Array(Schema.Int),
    trackSlug: Schema.Option(Schema.String),
  },
  execute: ({ trackSlug, ...form }) =>
    catchPanelFailure(
      Effect.gen(function* saveTrack() {
        const backend = yield* Backend;

        const saved = yield* Option.match(trackSlug, {
          onNone: () => backend.createTrack(form),
          onSome: (slug) => backend.updateTrack({ ...form, trackSlug: slug }),
        });

        return TrackFormMessage.SucceededSaveTrack({ slug: saved.slug });
      }).pipe(Effect.provide(Backend.layer)),
      (failure) => TrackFormMessage.FailedSaveTrack({ failure })
    ),
  messages: [
    TrackFormMessage.SucceededSaveTrack,
    TrackFormMessage.FailedSaveTrack,
  ],
});
