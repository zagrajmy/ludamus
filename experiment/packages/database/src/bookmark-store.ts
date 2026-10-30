import {
  BookmarkCount,
  BookmarkState,
  BookmarkStore,
  EventId,
  SessionId,
  SphereId,
  UserId,
} from "@zagrajmy/core";
import { DateTime, Effect, Layer, Option, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";

import {
  decodeFirst,
  decodeInput,
  decodeRows,
  IdRow,
  SqlBool,
  toSqlDateTime,
} from "./rows.js";
import { ROW_BUDGET } from "./sql-fragments.js";

const StateRow = Schema.Struct({
  ...BookmarkState.fields,
  bookmarked: SqlBool,
});

const ToggleInput = Schema.Struct({
  sessionId: SessionId,
  sphereId: SphereId,
  userId: UserId,
});

const OwnInput = Schema.Struct({ eventId: EventId, userId: UserId });

const StateInput = Schema.Struct({
  eventId: EventId,
  sessionId: SessionId,
  userId: Schema.NullOr(UserId),
});

export const makeBookmarkStore = Effect.gen(function* makeBookmarkStore() {
  const sql = yield* SqlClient;

  const stateOf = (options: {
    readonly operation: string;
    readonly sessionId: SessionId;
    readonly userId: UserId | null;
    readonly eventId: EventId | null;
  }) =>
    sql`
      SELECT COUNT(b.id) AS count, COALESCE(SUM(b.user_id = ${options.userId ?? -1}), 0) > 0 AS bookmarked
      FROM session_bookmark b JOIN session s ON s.id = b.session_id
      WHERE b.session_id = ${options.sessionId}
        AND ${options.eventId === null ? sql`1 = 1` : sql`s.event_id = ${options.eventId}`}
    `.pipe(
      decodeFirst(options.operation, StateRow),
      Effect.map(Option.getOrElse(() => ({ bookmarked: false, count: 0 })))
    );

  const toggle = Effect.fn("BookmarkStore.toggle")(function* toggle(
    options: typeof ToggleInput.Type
  ) {
    const input = yield* decodeInput(
      "BookmarkStore.toggle",
      ToggleInput
    )(options);

    const visible = yield* sql`
      SELECT s.id AS id FROM session s JOIN event e ON e.id = s.event_id
      WHERE s.id = ${input.sessionId} AND e.sphere_id = ${input.sphereId} AND s.deleted_at IS NULL
    `.pipe(decodeRows("BookmarkStore.toggle", IdRow));

    if (visible.length === 0) {
      return Option.none<BookmarkState>();
    }

    const deleted = yield* sql`
      DELETE FROM session_bookmark WHERE user_id = ${input.userId} AND session_id = ${input.sessionId} RETURNING id
    `.pipe(decodeRows("BookmarkStore.toggle", IdRow));

    if (deleted.length === 0) {
      const now = toSqlDateTime(yield* DateTime.now);
      yield* sql`
        INSERT INTO session_bookmark ${sql.insert({ creation_time: now, session_id: input.sessionId, user_id: input.userId })}
        ON CONFLICT (user_id, session_id) DO NOTHING
      `.pipe(decodeRows("BookmarkStore.toggle", IdRow));
    }

    return Option.some(
      yield* stateOf({
        eventId: null,
        operation: "BookmarkStore.toggle",
        sessionId: input.sessionId,
        userId: input.userId,
      })
    );
  });

  const bookmarkedSessionIds = Effect.fn("BookmarkStore.bookmarkedSessionIds")(
    function* bookmarkedSessionIds(options: typeof OwnInput.Type) {
      const input = yield* decodeInput(
        "BookmarkStore.bookmarkedSessionIds",
        OwnInput
      )(options);

      const rows = yield* sql`
      SELECT b.session_id AS id FROM session_bookmark b JOIN session s ON s.id = b.session_id
      WHERE b.user_id = ${input.userId} AND s.event_id = ${input.eventId}
      ORDER BY b.session_id LIMIT ${ROW_BUDGET.scheduledSessions}
    `.pipe(
        decodeRows(
          "BookmarkStore.bookmarkedSessionIds",
          Schema.Struct({ id: SessionId })
        )
      );

      return rows.map((row) => row.id);
    }
  );

  const counts = Effect.fn("BookmarkStore.counts")(function* counts(
    eventId: EventId
  ) {
    const valid = yield* decodeInput("BookmarkStore.counts", EventId)(eventId);

    return yield* sql`
      SELECT b.session_id AS sessionId, COUNT(b.id) AS count
      FROM session_bookmark b JOIN session s ON s.id = b.session_id
      WHERE s.event_id = ${valid} GROUP BY b.session_id ORDER BY b.session_id
      LIMIT ${ROW_BUDGET.scheduledSessions}
    `.pipe(decodeRows("BookmarkStore.counts", BookmarkCount));
  });

  const sessionState = Effect.fn("BookmarkStore.sessionState")(
    function* sessionState(options: typeof StateInput.Type) {
      const input = yield* decodeInput(
        "BookmarkStore.sessionState",
        StateInput
      )(options);

      return yield* stateOf({
        ...input,
        operation: "BookmarkStore.sessionState",
      });
    }
  );

  return BookmarkStore.of({
    bookmarkedSessionIds,
    counts,
    sessionState,
    toggle,
  });
});

export const BookmarkStoreLive = Layer.effect(BookmarkStore, makeBookmarkStore);
