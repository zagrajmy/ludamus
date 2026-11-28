import { FormError } from "@zagrajmy/core/contracts";
import { Schema } from "effect";

import { TrackFormFlags } from "./flags.js";

export const TrackFormModel = Schema.Struct({
  ...TrackFormFlags.fields,
  errors: Schema.Array(FormError),
  isSaving: Schema.Boolean,
});

export type TrackFormModel = typeof TrackFormModel.Type;

export const initTrackForm = (flags: TrackFormFlags): TrackFormModel => ({
  ...flags,
  errors: [],
  isSaving: false,
});

export const toggled = (
  ids: readonly number[],
  id: number,
  checked: boolean
): readonly number[] =>
  checked
    ? [...ids.filter((known) => known !== id), id]
    : ids.filter((known) => known !== id);
