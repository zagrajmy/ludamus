import { Schema } from "effect";
import { defineMessageUnion } from "foldkit/message";

import { PanelFailure } from "../failure.js";

export const TrackFormMessage = defineMessageUnion({
  ChangedName: { value: Schema.String },
  FailedSaveTrack: { failure: PanelFailure },
  SubmittedTrackForm: {},
  SucceededSaveTrack: { slug: Schema.String },
  ToggledManager: { checked: Schema.Boolean, id: Schema.Int },
  ToggledPublic: { checked: Schema.Boolean },
  ToggledSpace: { checked: Schema.Boolean, id: Schema.Int },
});

export type TrackFormMessage = typeof TrackFormMessage.Type;
