import { StoreError, StoreTransaction } from "@zagrajmy/core";
import { Effect, Layer } from "effect";
import { SqlClient } from "effect/sql/SqlClient";
import { isSqlError } from "effect/sql/SqlError";

export const makeStoreTransaction = Effect.gen(
  function* makeStoreTransaction() {
    const sql = yield* SqlClient;

    return StoreTransaction.of({
      atomic: (effect) =>
        sql.withTransaction(effect).pipe(
          Effect.mapError((failure) =>
            isSqlError(failure)
              ? new StoreError({
                  operation: "StoreTransaction.atomic",
                  reason: failure.reason._tag,
                })
              : failure
          )
        ),
    });
  }
);

export const StoreTransactionLive = Layer.effect(
  StoreTransaction,
  makeStoreTransaction
);
