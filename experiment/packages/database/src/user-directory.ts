import { User, UserDirectory, UserId } from "@zagrajmy/core";
import { Effect, Layer, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";
import type { Fragment } from "effect/sql/Statement";

import {
  decodeInput,
  decodeOne,
  decodeRows,
  SqlBool,
  SqlDateTime,
} from "./rows.js";
import { USER_SUMMARY_COLUMNS, UserSummaryRow } from "./shared-rows.js";
import { ROW_BUDGET } from "./sql-fragments.js";

const UserRow = Schema.Struct({
  ...User.fields,
  dateJoined: SqlDateTime,
  emailVerified: SqlBool,
  isActive: SqlBool,
  isStaff: SqlBool,
  isSuperuser: SqlBool,
  useGravatar: SqlBool,
});

const SponsorRow = Schema.Struct({
  ...UserSummaryRow.fields,
  memberId: UserId,
});

const USER_COLUMNS = `${USER_SUMMARY_COLUMNS("u")},
  u.age_band AS ageBand, u.date_joined AS dateJoined, u.discord_username AS discordUsername,
  u.email_verified AS emailVerified, u.is_active AS isActive, u.is_staff AS isStaff,
  u.is_superuser AS isSuperuser, u.pending_email AS pendingEmail`;

export const makeUserDirectory = Effect.gen(function* makeUserDirectory() {
  const sql = yield* SqlClient;
  const summary = sql.literal(USER_SUMMARY_COLUMNS("u"));

  const readWhere = (operation: string, key: string, where: Fragment) =>
    sql`SELECT ${sql.literal(USER_COLUMNS)} FROM user u WHERE ${where}`.pipe(
      decodeOne({ entity: "User", key, operation, row: UserRow })
    );

  const readBySlug = Effect.fn("UserDirectory.readBySlug")(function* readBySlug(
    slug: string
  ) {
    const valid = yield* decodeInput(
      "UserDirectory.readBySlug",
      Schema.String
    )(slug);

    return yield* readWhere(
      "UserDirectory.readBySlug",
      valid,
      sql`u.slug = ${valid}`
    );
  });

  const readById = Effect.fn("UserDirectory.readById")(function* readById(
    id: UserId
  ) {
    const valid = yield* decodeInput("UserDirectory.readById", UserId)(id);

    return yield* readWhere(
      "UserDirectory.readById",
      String(valid),
      sql`u.id = ${valid}`
    );
  });

  const listByIds = Effect.fn("UserDirectory.listByIds")(function* listByIds(
    ids: readonly UserId[]
  ) {
    const valid = yield* decodeInput(
      "UserDirectory.listByIds",
      Schema.Array(UserId)
    )(ids);

    if (valid.length === 0) {
      return [];
    }

    return yield* sql`
      SELECT ${summary} FROM user u WHERE ${sql.in("u.id", valid)} ORDER BY u.id LIMIT ${valid.length}
    `.pipe(decodeRows("UserDirectory.listByIds", UserSummaryRow));
  });

  const companionsOf = Effect.fn("UserDirectory.companionsOf")(
    function* companionsOf(managerId: UserId) {
      const valid = yield* decodeInput(
        "UserDirectory.companionsOf",
        UserId
      )(managerId);

      return yield* sql`
      SELECT ${summary} FROM user u WHERE u.manager_id = ${valid} AND u.user_type = 'connected'
      ORDER BY u.id LIMIT ${ROW_BUDGET.parties}
    `.pipe(decodeRows("UserDirectory.companionsOf", UserSummaryRow));
    }
  );

  const sponsorsOf = Effect.fn("UserDirectory.sponsorsOf")(function* sponsorsOf(
    memberIds: readonly UserId[]
  ) {
    const valid = yield* decodeInput(
      "UserDirectory.sponsorsOf",
      Schema.Array(UserId)
    )(memberIds);

    if (valid.length === 0) {
      return [];
    }

    const rows = yield* sql`
      SELECT c.id AS memberId, ${summary}
      FROM user c JOIN user u ON u.id = c.manager_id
      WHERE ${sql.in("c.id", valid)} AND c.user_type = 'connected'
      ORDER BY c.id LIMIT ${valid.length}
    `.pipe(decodeRows("UserDirectory.sponsorsOf", SponsorRow));

    return rows.map(({ memberId, ...sponsor }) => ({ memberId, sponsor }));
  });

  return UserDirectory.of({
    companionsOf,
    listByIds,
    readById,
    readBySlug,
    sponsorsOf,
  });
});

export const UserDirectoryLive = Layer.effect(UserDirectory, makeUserDirectory);
