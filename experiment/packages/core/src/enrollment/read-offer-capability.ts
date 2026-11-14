import { implement } from "@zagrajmy/capability/implement";
import { Effect, Option } from "effect";

import { readOfferContract } from "../contracts.js";
import { NotFound } from "../ports/store-error.js";
import type { OfferView } from "./api.js";
import { offerByToken } from "./offer-resolution.js";

export const readOffer = implement(readOfferContract, ({ token }) =>
  Effect.gen(function* readOfferHandler() {
    const offer = yield* offerByToken(token);

    if (Option.isNone(offer)) {
      return yield* new NotFound({ entity: "Offer", key: "token" });
    }

    const view: OfferView = {
      eventSlug: offer.value.eventSlug,
      offerExpiresAt: offer.value.offerExpiresAt,
      sessionId: offer.value.sessionId,
      sessionTitle: offer.value.sessionTitle,
    };

    return view;
  })
);
