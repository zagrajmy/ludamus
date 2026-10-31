import { Effect, Option } from "effect";

import { CurrentSphere } from "../ports/current-sphere.js";
import type { OfferResolution } from "./api.js";
import { PromotionStore } from "./ports.js";
import type { ClaimResult } from "./schemas.js";

export const offerQuery = (token: string) =>
  CurrentSphere.pipe(Effect.map((sphere) => ({ sphereId: sphere.id, token })));

export const offerByToken = (token: string) =>
  Effect.gen(function* readOfferByToken() {
    const store = yield* PromotionStore;
    const query = yield* offerQuery(token);

    return token === "" ? Option.none() : yield* store.readOfferByToken(query);
  });

export const resolution = (
  result: ClaimResult,
  success: "claimed" | "declined"
): OfferResolution => ({
  eventSlug: result.eventSlug,
  outcome: result.success ? success : (result.reason ?? "not_found"),
  sessionId: result.sessionId,
});
