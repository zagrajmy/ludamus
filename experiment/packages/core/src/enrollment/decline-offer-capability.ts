import { implement } from "@zagrajmy/capability/implement";
import { Effect } from "effect";

import { declineOfferContract } from "../contracts.js";
import { offerQuery, resolution } from "./offer-resolution.js";
import { declineOffer as declineWith } from "./promotion-service.js";

export const declineOffer = implement(declineOfferContract, ({ token }) =>
  offerQuery(token).pipe(
    Effect.flatMap(declineWith),
    Effect.map((result) => resolution(result, "declined")),
    Effect.tap((resolved) =>
      Effect.logInfo("offer decline").pipe(
        Effect.annotateLogs({
          outcome: resolved.outcome,
          sessionId: resolved.sessionId ?? "none",
        })
      )
    )
  )
);
