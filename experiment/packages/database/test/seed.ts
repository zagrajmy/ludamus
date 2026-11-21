import { DateTime, Duration, Effect, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";

import { SqlDateTime } from "../src/rows.js";

const AnchorRow = Schema.Struct({ anchor: SqlDateTime });

export const seedNow = Effect.gen(function* seedNow() {
  const sql = yield* SqlClient;

  const rows = yield* sql`SELECT MAX(date_joined) AS anchor FROM user`.pipe(
    Effect.flatMap(Schema.decodeUnknownEffect(Schema.Array(AnchorRow)))
  );

  const anchor = rows[0]?.anchor ?? DateTime.makeUnsafe(0);

  return DateTime.addDuration(anchor, Duration.hours(1));
});

export const brand =
  <A>(schema: Schema.Codec<A, number>) =>
  (value: number): A =>
    Schema.decodeSync(schema)(value);

export const countRows = (
  table: "session" | "track" | "facilitator" | "session_participant"
) =>
  Effect.gen(function* countTable() {
    const sql = yield* SqlClient;

    const rows = yield* sql`SELECT COUNT(*) AS count FROM ${sql(table)}`.pipe(
      Effect.flatMap(
        Schema.decodeUnknownEffect(
          Schema.Array(Schema.Struct({ count: Schema.Int }))
        )
      )
    );

    return rows[0]?.count ?? -1;
  });
