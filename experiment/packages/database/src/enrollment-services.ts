import {
  MembershipApiError,
  EnrollmentStoreError,
} from "@zagrajmy/core/enrollment/errors";
import {
  ClaimTokens,
  EnrollmentTransaction,
  OfferExpiryScheduler,
  TicketApi,
} from "@zagrajmy/core/enrollment/ports";
import { DateTime, Effect, Layer } from "effect";
import { SqlClient } from "effect/sql/SqlClient";
import { isSqlError } from "effect/sql/SqlError";

const CLAIM_TOKEN_BYTES = 48;

export const EnrollmentTransactionLive = Layer.effect(
  EnrollmentTransaction,
  Effect.gen(function* makeEnrollmentTransaction() {
    const sql = yield* SqlClient;

    return EnrollmentTransaction.of({
      atomic: (effect) =>
        sql.withTransaction(effect).pipe(
          Effect.mapError((failure) =>
            isSqlError(failure)
              ? new EnrollmentStoreError({
                  operation: "EnrollmentTransaction.atomic",
                  reason: failure.reason._tag,
                })
              : failure
          )
        ),
    });
  })
);

export const ClaimTokensLive = Layer.succeed(ClaimTokens, {
  next: Effect.sync(() =>
    Buffer.from(
      crypto.getRandomValues(new Uint8Array(CLAIM_TOKEN_BYTES))
    ).toString("base64url")
  ),
});

export const OfferExpirySchedulerLive = Layer.succeed(OfferExpiryScheduler, {
  scheduleExpiry: (expiry) =>
    Effect.logInfo(
      "offer deadline recorded; the expireOffers sweep releases it"
    ).pipe(
      Effect.annotateLogs({
        participationId: expiry.participationId,
        runAt: DateTime.formatIso(expiry.runAt),
      })
    ),
});

export const NoTicketApiLive = Layer.succeed(TicketApi, {
  fetchMembershipCount: () =>
    Effect.fail(new MembershipApiError({ reason: "no ticketing integration" })),
});
