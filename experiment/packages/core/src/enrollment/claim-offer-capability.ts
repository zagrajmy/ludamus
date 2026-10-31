import { implement } from "@zagrajmy/capability/implement";
import { Effect } from "effect";

import { claimOfferContract } from "../contracts.js";
import { offerQuery, resolution } from "./offer-resolution.js";
import { claimOffer as claimWith } from "./promotion-service.js";

export const claimOffer = implement(claimOfferContract, ({ token }) =>
  offerQuery(token).pipe(
    Effect.flatMap(claimWith),
    Effect.map((result) => resolution(result, "claimed")),
    Effect.tap((resolved) =>
      Effect.logInfo("offer claim").pipe(
        Effect.annotateLogs({
          outcome: resolved.outcome,
          sessionId: resolved.sessionId ?? "none",
        })
      )
    )
  )
);
