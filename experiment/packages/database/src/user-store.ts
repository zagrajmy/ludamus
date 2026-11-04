import type { StoreError } from "@zagrajmy/core";
import { Context, Effect, Layer, Option, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";

import { decodeRows } from "./rows.js";

export const UserRow = Schema.Struct({
  email: Schema.String,
  id: Schema.Int,
  isActive: Schema.Number,
  isSuperuser: Schema.Number,
  name: Schema.String,
  password: Schema.String,
  slug: Schema.String,
  username: Schema.String,
});

export type UserRow = typeof UserRow.Type;

export class UserStore extends Context.Service<
  UserStore,
  {
    readonly byId: (
      id: number
    ) => Effect.Effect<Option.Option<UserRow>, StoreError>;
  }
>()("@zagrajmy/database/UserStore") {}

export const UserStoreLive = Layer.effect(
  UserStore,
  Effect.gen(function* makeUserStore() {
    const sql = yield* SqlClient;

    return UserStore.of({
      byId: (id) =>
        sql`
          SELECT id, username, email, name, slug, password,
                 is_active AS isActive, is_superuser AS isSuperuser
          FROM user WHERE id = ${id}
        `.pipe(
          decodeRows("UserStore.byId", UserRow),
          Effect.map((rows) => Option.fromNullishOr(rows[0]))
        ),
    });
  })
);
