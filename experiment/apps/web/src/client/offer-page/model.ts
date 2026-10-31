import { Schema } from "effect";

import { OfferPageFlags } from "./flags.js";
import type { OfferPageFlags as Flags } from "./flags.js";

export const OfferPageModel = Schema.Struct({
  ...OfferPageFlags.fields,
  busy: Schema.Boolean,
});

export type OfferPageModel = typeof OfferPageModel.Type;

export const initOfferPage = (flags: Flags): OfferPageModel => ({
  ...flags,
  busy: false,
});
