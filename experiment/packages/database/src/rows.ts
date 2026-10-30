import { StoreError } from "@zagrajmy/core";
import { Effect, Schema } from "effect";
import type { SqlClient } from "effect/sql/SqlClient";
import type { Statement } from "effect/sql/Statement";

export const decodeRows =
  <A, I>(operation: string, row: Schema.Codec<A, I>) =>
  <E>(
    statement: Effect.Effect<ReadonlyArray<unknown>, E>
  ): Effect.Effect<ReadonlyArray<A>, StoreError> =>
    statement.pipe(
      Effect.flatMap(Schema.decodeUnknownEffect(Schema.Array(row))),
      Effect.mapError((cause) => new StoreError({ operation, reason: String(cause) }))
    );

export type Sql = SqlClient;
export type SqlStatement<A> = Statement<A>;
