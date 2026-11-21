import type { EventBan } from "@zagrajmy/core";
import {
  EVENT_BAN_REASON_MAX_LENGTH,
  EventBanId,
  EventId,
  SafetyStore,
  SessionId,
  UserId,
} from "@zagrajmy/core";
import { DateTime, Effect, Layer, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";

import {
  decodeInput,
  decodeRows,
  IdRow,
  SqlDateTime,
  storeFailure,
  toSqlDateTime,
} from "./rows.js";
import { USER_SUMMARY_COLUMNS, UserSummaryRow } from "./shared-rows.js";
import { ROW_BUDGET } from "./sql-fragments.js";

const BanRow = Schema.Struct({
  ...UserSummaryRow.fields,
  banCreatedAt: SqlDateTime,
  banId: EventBanId,
  banReason: Schema.String,
  eventId: EventId,
});

const WarningRow = Schema.Struct({
  ...UserSummaryRow.fields,
  shadowbannedAt: SqlDateTime,
});

const UserIdRow = Schema.Struct({ id: UserId });

const EventIdRow = Schema.Struct({ id: EventId });

const ShadowbanInput = Schema.Struct({
  banned: Schema.Boolean,
  ownerId: UserId,
  targetId: UserId,
});

const WarningInput = Schema.Struct({ sessionId: SessionId, viewerId: UserId });

const BanCheckInput = Schema.Struct({ eventId: EventId, userId: UserId });

const BannedEventsInput = Schema.Struct({
  eventIds: Schema.Array(EventId),
  userId: UserId,
});

const BanInput = Schema.Struct({
  eventId: EventId,
  reason: Schema.String,
  userId: UserId,
});

const UnbanInput = Schema.Struct({ eventId: EventId, id: EventBanId });

export const makeSafetyStore = Effect.gen(function* makeSafetyStore() {
  const sql = yield* SqlClient;
  const summary = sql.literal(USER_SUMMARY_COLUMNS("u"));

  const bannedUserIds = Effect.fn("SafetyStore.bannedUserIds")(
    function* bannedUserIds(ownerId: UserId) {
      const valid = yield* decodeInput(
        "SafetyStore.bannedUserIds",
        UserId
      )(ownerId);

      const rows = yield* sql`
      SELECT target_id AS id FROM shadowban WHERE owner_id = ${valid} ORDER BY target_id LIMIT ${ROW_BUDGET.bans}
    `.pipe(decodeRows("SafetyStore.bannedUserIds", UserIdRow));

      return rows.map((row) => row.id);
    }
  );

  const banningOwnerIds = Effect.fn("SafetyStore.banningOwnerIds")(
    function* banningOwnerIds(targetId: UserId) {
      const valid = yield* decodeInput(
        "SafetyStore.banningOwnerIds",
        UserId
      )(targetId);

      const rows = yield* sql`
      SELECT owner_id AS id FROM shadowban WHERE target_id = ${valid} ORDER BY owner_id LIMIT ${ROW_BUDGET.bans}
    `.pipe(decodeRows("SafetyStore.banningOwnerIds", UserIdRow));

      return rows.map((row) => row.id);
    }
  );

  const setShadowban = Effect.fn("SafetyStore.setShadowban")(
    function* setShadowban(options: typeof ShadowbanInput.Type) {
      const input = yield* decodeInput(
        "SafetyStore.setShadowban",
        ShadowbanInput
      )(options);

      if (input.ownerId === input.targetId) {
        return;
      }

      const now = toSqlDateTime(yield* DateTime.now);
      yield* (
        input.banned
          ? sql`INSERT INTO shadowban ${sql.insert({ created_at: now, owner_id: input.ownerId, target_id: input.targetId })}
            ON CONFLICT (owner_id, target_id) DO NOTHING`
          : sql`DELETE FROM shadowban WHERE owner_id = ${input.ownerId} AND target_id = ${input.targetId}`
      ).pipe(storeFailure("SafetyStore.setShadowban"));
    }
  );

  const sessionShadowbanWarnings = Effect.fn(
    "SafetyStore.sessionShadowbanWarnings"
  )(function* sessionShadowbanWarnings(options: typeof WarningInput.Type) {
    const input = yield* decodeInput(
      "SafetyStore.sessionShadowbanWarnings",
      WarningInput
    )(options);

    const rows = yield* sql`
        SELECT ${summary}, b.created_at AS shadowbannedAt
        FROM shadowban b JOIN user u ON u.id = b.target_id
        WHERE b.owner_id = ${input.viewerId} AND EXISTS (
          SELECT 1 FROM session_participant p WHERE p.user_id = b.target_id
            AND p.session_id = ${input.sessionId} AND p.status IN ('confirmed', 'waiting', 'offered'))
        ORDER BY u.name, u.id LIMIT ${ROW_BUDGET.bans}
      `.pipe(decodeRows("SafetyStore.sessionShadowbanWarnings", WarningRow));

    return rows.map(({ shadowbannedAt, ...user }) => ({
      shadowbannedAt,
      user,
    }));
  });

  const listEventBans = Effect.fn("SafetyStore.listEventBans")(
    function* listEventBans(eventId: EventId) {
      const valid = yield* decodeInput(
        "SafetyStore.listEventBans",
        EventId
      )(eventId);

      const rows = yield* sql`
      SELECT b.id AS banId, b.event_id AS eventId, b.reason AS banReason, b.created_at AS banCreatedAt, ${summary}
      FROM event_ban b JOIN user u ON u.id = b.user_id
      WHERE b.event_id = ${valid} ORDER BY u.name, b.id LIMIT ${ROW_BUDGET.bans}
    `.pipe(decodeRows("SafetyStore.listEventBans", BanRow));

      return rows.map(
        ({
          banId,
          eventId: event,
          banReason,
          banCreatedAt,
          ...user
        }): EventBan => ({
          createdAt: banCreatedAt,
          eventId: event,
          id: banId,
          reason: banReason,
          user,
        })
      );
    }
  );

  const isBanned = Effect.fn("SafetyStore.isBanned")(function* isBanned(
    options: typeof BanCheckInput.Type
  ) {
    const input = yield* decodeInput(
      "SafetyStore.isBanned",
      BanCheckInput
    )(options);

    const rows = yield* sql`
      SELECT id FROM event_ban WHERE event_id = ${input.eventId} AND user_id = ${input.userId} LIMIT 1
    `.pipe(decodeRows("SafetyStore.isBanned", IdRow));

    return rows.length > 0;
  });

  const bannedEventIds = Effect.fn("SafetyStore.bannedEventIds")(
    function* bannedEventIds(options: typeof BannedEventsInput.Type) {
      const input = yield* decodeInput(
        "SafetyStore.bannedEventIds",
        BannedEventsInput
      )(options);

      if (input.eventIds.length === 0) {
        return [];
      }

      const rows = yield* sql`
      SELECT event_id AS id FROM event_ban WHERE user_id = ${input.userId} AND ${sql.in("event_id", input.eventIds)}
      ORDER BY event_id LIMIT ${input.eventIds.length}
    `.pipe(decodeRows("SafetyStore.bannedEventIds", EventIdRow));

      return rows.map((row) => row.id);
    }
  );

  const ban = Effect.fn("SafetyStore.ban")(function* ban(
    options: typeof BanInput.Type
  ) {
    const input = yield* decodeInput("SafetyStore.ban", BanInput)(options);
    const now = toSqlDateTime(yield* DateTime.now);
    yield* sql`
      INSERT INTO event_ban ${sql.insert({
        created_at: now,
        event_id: input.eventId,
        reason: input.reason.slice(0, EVENT_BAN_REASON_MAX_LENGTH),
        user_id: input.userId,
      })}
      ON CONFLICT (event_id, user_id) DO UPDATE SET reason = excluded.reason
    `.pipe(storeFailure("SafetyStore.ban"));
  });

  const unban = Effect.fn("SafetyStore.unban")(function* unban(
    options: typeof UnbanInput.Type
  ) {
    const input = yield* decodeInput("SafetyStore.unban", UnbanInput)(options);
    yield* sql`DELETE FROM event_ban WHERE id = ${input.id} AND event_id = ${input.eventId}`.pipe(
      storeFailure("SafetyStore.unban")
    );
  });

  return SafetyStore.of({
    ban,
    bannedEventIds,
    bannedUserIds,
    banningOwnerIds,
    isBanned,
    listEventBans,
    sessionShadowbanWarnings,
    setShadowban,
    unban,
  });
});

export const SafetyStoreLive = Layer.effect(SafetyStore, makeSafetyStore);
