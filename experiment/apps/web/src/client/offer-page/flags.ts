import { OfferView } from "@zagrajmy/core/contracts";
import { Schema } from "effect";

import { Locale } from "../../ui/i18n.js";

export const OfferPageFlags = Schema.Struct({
  deadlineLabel: Schema.String,
  locale: Locale,
  offer: OfferView,
  token: Schema.String,
});

export type OfferPageFlags = typeof OfferPageFlags.Type;
