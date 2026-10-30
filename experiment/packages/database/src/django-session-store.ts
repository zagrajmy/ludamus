import { StoreError } from "@zagrajmy/core";
import { Context, Effect, Layer, Option, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";

import { decodeRows } from "./rows.js";

export const DjangoSessionRow = Schema.Struct({
  expireDate: Schema.String,
  sessionData: Schema.String,
  sessionKey: Schema.String,
});
export type DjangoSessionRow = typeof DjangoSessionRow.Type;

export class DjangoSessionStore extends Context.Service<
  DjangoSessionStore,
  {
    readonly read: (
      sessionKey: string
    ) => Effect.Effect<Option.Option<DjangoSessionRow>, StoreError>;
  }
>()("@zagrajmy/database/DjangoSessionStore") {}

export const DjangoSessionStoreLive = Layer.effect(
  DjangoSessionStore,
  Effect.gen(function* makeDjangoSessionStore() {
    const sql = yield* SqlClient;

    return DjangoSessionStore.of({
      read: (sessionKey) =>
        sql`
          SELECT session_key AS sessionKey, session_data AS sessionData,
                 expire_date AS expireDate
          FROM django_session WHERE session_key = ${sessionKey}
        `.pipe(
          decodeRows("DjangoSessionStore.read", DjangoSessionRow),
          Effect.map((rows) => Option.fromNullishOr(rows[0]))
        ),
    });
  })
);
