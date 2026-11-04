import {
  AgendaItemId,
  AgendaItemStore,
  EventId,
  NewAgendaItem,
  SessionId,
  SpaceId,
  StoreError,
} from "@zagrajmy/core";
import { Effect, Layer, Option, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";

import {
  decodeFirst,
  decodeInput,
  decodeRows,
  IdRow,
  requireRow,
  toSqlDateTime,
} from "./rows.js";
import { AgendaItemRow } from "./shared-rows.js";
import { ROW_BUDGET } from "./sql-fragments.js";

const AGENDA_COLUMNS = `
  a.id AS id, a.session_id AS sessionId, a.space_id AS spaceId,
  a.start_time AS startTime, a.end_time AS endTime,
  s.schedule_confirmed AS scheduleConfirmed`;

const OverlapInput = Schema.Struct({
  endTime: Schema.DateTimeUtc,
  excludeSessionId: Schema.NullOr(SessionId),
  spaceId: SpaceId,
  startTime: Schema.DateTimeUtc,
});

const ScopeInput = Schema.Struct({ eventId: EventId, id: AgendaItemId });

const NewIdRow = Schema.Struct({ id: AgendaItemId });

export const makeAgendaItemStore = Effect.gen(function* makeAgendaItemStore() {
  const sql = yield* SqlClient;
  const columns = sql.literal(AGENDA_COLUMNS);

  const readBySession = Effect.fn("AgendaItemStore.readBySession")(
    function* readBySession(sessionId: SessionId) {
      const valid = yield* decodeInput(
        "AgendaItemStore.readBySession",
        SessionId
      )(sessionId);

      return yield* sql`
      SELECT ${columns} FROM agenda_item a JOIN session s ON s.id = a.session_id WHERE a.session_id = ${valid}
    `.pipe(decodeFirst("AgendaItemStore.readBySession", AgendaItemRow));
    }
  );

  const listOverlappingInSpace = Effect.fn(
    "AgendaItemStore.listOverlappingInSpace"
  )(function* listOverlappingInSpace(options: typeof OverlapInput.Type) {
    const input = yield* decodeInput(
      "AgendaItemStore.listOverlappingInSpace",
      OverlapInput
    )(options);

    const start = toSqlDateTime(input.startTime);
    const end = toSqlDateTime(input.endTime);

    const excluded =
      input.excludeSessionId === null
        ? sql`1 = 1`
        : sql`a.session_id <> ${input.excludeSessionId}`;

    return yield* sql`
      SELECT ${columns} FROM agenda_item a JOIN session s ON s.id = a.session_id
      WHERE a.space_id = ${input.spaceId} AND a.start_time < ${end} AND a.end_time > ${start} AND ${excluded}
      ORDER BY a.start_time, a.id
      LIMIT ${ROW_BUDGET.scheduledSessions}
    `.pipe(decodeRows("AgendaItemStore.listOverlappingInSpace", AgendaItemRow));
  });

  const create = Effect.fn("AgendaItemStore.create")(function* create(
    item: typeof NewAgendaItem.Type
  ) {
    const input = yield* decodeInput(
      "AgendaItemStore.create",
      NewAgendaItem
    )(item);

    const rows = yield* sql`
      INSERT INTO agenda_item ${sql.insert({
        end_time: toSqlDateTime(input.endTime),
        session_confirmed: input.sessionConfirmed ? 1 : 0,
        session_id: input.sessionId,
        space_id: input.spaceId,
        start_time: toSqlDateTime(input.startTime),
      })} RETURNING id
    `.pipe(decodeRows("AgendaItemStore.create", NewIdRow));

    return yield* Option.match(Option.fromNullishOr(rows[0]), {
      onNone: () =>
        Effect.fail(
          new StoreError({
            operation: "AgendaItemStore.create",
            reason: "insert returned no id",
          })
        ),
      onSome: (row) => Effect.succeed(row.id),
    });
  });

  const remove = Effect.fn("AgendaItemStore.delete")(function* remove(
    scope: typeof ScopeInput.Type
  ) {
    const input = yield* decodeInput(
      "AgendaItemStore.delete",
      ScopeInput
    )(scope);

    const rows = yield* sql`
      DELETE FROM agenda_item WHERE id = ${input.id}
        AND session_id IN (SELECT id FROM session WHERE event_id = ${input.eventId})
      RETURNING id
    `.pipe(decodeRows("AgendaItemStore.delete", IdRow));

    yield* requireRow({ entity: "AgendaItem", key: String(input.id) })(rows);
  });

  return AgendaItemStore.of({
    create,
    delete: remove,
    listOverlappingInSpace,
    readBySession,
  });
});

export const AgendaItemStoreLive = Layer.effect(
  AgendaItemStore,
  makeAgendaItemStore
);
