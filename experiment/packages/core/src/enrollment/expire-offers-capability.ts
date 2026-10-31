import { implement } from "@zagrajmy/capability/implement";
import { DateTime, Effect } from "effect";

import { expireOffersContract } from "../contracts.js";
import { CurrentSphere } from "../ports/current-sphere.js";
import type { ExpiredOffers } from "./api.js";
import { PromotionStore } from "./ports.js";
import { expireOffer } from "./promotion-service.js";

export const expireOffers = implement(expireOffersContract, () =>
  Effect.gen(function* expireOffersHandler() {
    const sphere = yield* CurrentSphere;
    const store = yield* PromotionStore;
    const now = yield* DateTime.now;
    const lapsed = yield* store.listLapsedOffers({ now, sphereId: sphere.id });

    const results = yield* Effect.all(lapsed.map((item) => expireOffer(item)));

    const swept: ExpiredOffers = {
      expired: lapsed.length,
      promoted: results.reduce(
        (total, result) =>
          total + result.promoted.length + result.offered.length,
        0
      ),
    };

    yield* Effect.logInfo("lapsed offers swept").pipe(
      Effect.annotateLogs({ ...swept, sphereId: sphere.id })
    );

    return swept;
  })
);
