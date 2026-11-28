import {
  CHANGE_LOG_PAGE_SIZE,
  ChangeLogCursor,
  ChangeLogStore,
  ContentFieldChange,
  EventId,
  FacilitatorChangeLogEntry,
  NewFacilitatorChangeLog,
  NewScheduleChangeLog,
  ScheduleChangeLogEntry,
  ScheduleChangeLogId,
  SessionId,
  StoreError,
} from "@zagrajmy/core";
import {
  DateTime,
  Effect,
  Layer,
  Option,
  Schema,
  SchemaTransformation,
} from "effect";
import { SqlClient } from "effect/sql/SqlClient";
import type { Fragment } from "effect/sql/Statement";

import {
  decodeInput,
  decodeRows,
  pythonJson,
  SqlBool,
  SqlDateTime,
  storeFailure,
  toSqlDateTime,
} from "./rows.js";

const StoredChange = Schema.Struct({
  field: Schema.String,
  field_id: ContentFieldChange.fields.fieldId,
  new: ContentFieldChange.fields.new,
  old: ContentFieldChange.fields.old,
});

const ChangeFromStored = StoredChange.pipe(
  Schema.decodeTo(
    ContentFieldChange,
    SchemaTransformation.transform({
      decode: (stored: typeof StoredChange.Type) => ({
        field: stored.field,
        fieldId: stored.field_id,
        new: stored.new,
        old: stored.old,
      }),
      encode: (change: typeof ContentFieldChange.Type) => ({
        field: change.field,
        field_id: change.fieldId,
        new: change.new,
        old: change.old,
      }),
    })
  )
);

const FacilitatorLogRow = Schema.Struct({
  ...FacilitatorChangeLogEntry.fields,
  changes: Schema.fromJsonString(Schema.Array(ChangeFromStored)),
  creationTime: SqlDateTime,
});

const ScheduleLogRow = Schema.Struct({
  ...ScheduleChangeLogEntry.fields,
  acknowledgementTime: Schema.NullOr(SqlDateTime),
  creationTime: SqlDateTime,
  important: SqlBool,
  newEndTime: Schema.NullOr(SqlDateTime),
  newStartTime: Schema.NullOr(SqlDateTime),
  oldEndTime: Schema.NullOr(SqlDateTime),
  oldStartTime: Schema.NullOr(SqlDateTime),
});

const SCHEDULE_COLUMNS = `
  l.id AS id, l.event_id AS eventId, l.session_id AS sessionId, s.title AS sessionTitle,
  l.user_id AS userId, COALESCE(u.name, '') AS userName, l.action AS action,
  l.old_space_id AS oldSpaceId, os.name AS oldSpaceName,
  l.new_space_id AS newSpaceId, ns.name AS newSpaceName,
  l.old_start_time AS oldStartTime, l.old_end_time AS oldEndTime,
  l.new_start_time AS newStartTime, l.new_end_time AS newEndTime,
  l.creation_time AS creationTime, l.moved_from_id AS movedFromId,
  l.acknowledgement_time AS acknowledgementTime,
  COALESCE(ack.name, '') AS acknowledgedByName, l.important AS important`;

const SCHEDULE_FROM = `
  FROM schedule_change_log l
  JOIN session s ON s.id = l.session_id
  LEFT JOIN user u ON u.id = l.user_id
  LEFT JOIN space os ON os.id = l.old_space_id
  LEFT JOIN space ns ON ns.id = l.new_space_id
  LEFT JOIN user ack ON ack.id = l.acknowledged_by_id`;

const EventPage = Schema.Struct({
  before: Schema.NullOr(ChangeLogCursor),
  key: EventId,
});

const SessionPage = Schema.Struct({
  before: Schema.NullOr(ChangeLogCursor),
  key: SessionId,
});

const IdRow = Schema.Struct({ id: ScheduleChangeLogId });

const optionalTime = (value: DateTime.Utc | null) =>
  value === null ? null : toSqlDateTime(value);

export const makeChangeLogStore = Effect.gen(function* makeChangeLogStore() {
  const sql = yield* SqlClient;

  const keyset = (before: typeof ChangeLogCursor.Type | null): Fragment =>
    before === null
      ? sql`1 = 1`
      : sql`(l.creation_time < ${toSqlDateTime(before.creationTime)}
          OR (l.creation_time = ${toSqlDateTime(before.creationTime)} AND l.id < ${before.id}))`;

  const logFacilitatorChange = Effect.fn("ChangeLogStore.logFacilitatorChange")(
    function* logFacilitatorChange(entry: typeof NewFacilitatorChangeLog.Type) {
      const input = yield* decodeInput(
        "ChangeLogStore.logFacilitatorChange",
        NewFacilitatorChangeLog
      )(entry);

      const now = toSqlDateTime(yield* DateTime.now);
      yield* sql`
      INSERT INTO facilitator_change_log ${sql.insert({
        changes: pythonJson(
          input.changes.map((change) => ({
            field: change.field,
            field_id: change.fieldId,
            new: change.new,
            old: change.old,
          }))
        ),
        creation_time: now,
        event_id: input.eventId,
        facilitator_id: input.facilitatorId,
        user_id: input.userId,
      })}
    `.pipe(storeFailure("ChangeLogStore.logFacilitatorChange"));
    }
  );

  const listFacilitatorChanges = Effect.fn(
    "ChangeLogStore.listFacilitatorChanges"
  )(function* listFacilitatorChanges(page: typeof EventPage.Type) {
    const input = yield* decodeInput(
      "ChangeLogStore.listFacilitatorChanges",
      EventPage
    )(page);

    return yield* sql`
      SELECT l.id AS id, l.event_id AS eventId, l.facilitator_id AS facilitatorId,
        f.display_name AS facilitatorName, l.user_id AS userId, COALESCE(u.name, '') AS userName,
        l.changes AS changes, l.creation_time AS creationTime
      FROM facilitator_change_log l
      JOIN facilitator f ON f.id = l.facilitator_id
      LEFT JOIN user u ON u.id = l.user_id
      WHERE l.event_id = ${input.key} AND ${keyset(input.before)}
      ORDER BY l.creation_time DESC, l.id DESC
      LIMIT ${CHANGE_LOG_PAGE_SIZE}
    `.pipe(
      decodeRows("ChangeLogStore.listFacilitatorChanges", FacilitatorLogRow)
    );
  });

  const logScheduleChange = Effect.fn("ChangeLogStore.logScheduleChange")(
    function* logScheduleChange(entry: typeof NewScheduleChangeLog.Type) {
      const input = yield* decodeInput(
        "ChangeLogStore.logScheduleChange",
        NewScheduleChangeLog
      )(entry);

      const now = toSqlDateTime(yield* DateTime.now);

      const rows = yield* sql`
      INSERT INTO schedule_change_log ${sql.insert({
        acknowledged_by_id: null,
        acknowledgement_time: null,
        action: input.action,
        creation_time: now,
        event_id: input.eventId,
        important: 0,
        moved_from_id: input.movedFromId,
        new_end_time: optionalTime(input.newEndTime),
        new_space_id: input.newSpaceId,
        new_start_time: optionalTime(input.newStartTime),
        old_end_time: optionalTime(input.oldEndTime),
        old_space_id: input.oldSpaceId,
        old_start_time: optionalTime(input.oldStartTime),
        session_id: input.sessionId,
        user_id: input.userId,
      })} RETURNING id
    `.pipe(decodeRows("ChangeLogStore.logScheduleChange", IdRow));

      return yield* Option.match(Option.fromNullishOr(rows[0]), {
        onNone: () =>
          Effect.fail(
            new StoreError({
              operation: "ChangeLogStore.logScheduleChange",
              reason: "insert returned no id",
            })
          ),
        onSome: (row) => Effect.succeed(row.id),
      });
    }
  );

  const scheduleWhere = (
    operation: string,
    where: Fragment,
    before: typeof ChangeLogCursor.Type | null
  ) =>
    sql`
      SELECT ${sql.literal(SCHEDULE_COLUMNS)} ${sql.literal(SCHEDULE_FROM)}
      WHERE ${where} AND ${keyset(before)}
      ORDER BY l.creation_time DESC, l.id DESC
      LIMIT ${CHANGE_LOG_PAGE_SIZE}
    `.pipe(decodeRows(operation, ScheduleLogRow));

  const listScheduleChanges = Effect.fn("ChangeLogStore.listScheduleChanges")(
    function* listScheduleChanges(page: typeof EventPage.Type) {
      const input = yield* decodeInput(
        "ChangeLogStore.listScheduleChanges",
        EventPage
      )(page);

      return yield* scheduleWhere(
        "ChangeLogStore.listScheduleChanges",
        sql`l.event_id = ${input.key}`,
        input.before
      );
    }
  );

  const listScheduleChangesBySession = Effect.fn(
    "ChangeLogStore.listScheduleChangesBySession"
  )(function* listScheduleChangesBySession(page: typeof SessionPage.Type) {
    const input = yield* decodeInput(
      "ChangeLogStore.listScheduleChangesBySession",
      SessionPage
    )(page);

    return yield* scheduleWhere(
      "ChangeLogStore.listScheduleChangesBySession",
      sql`l.session_id = ${input.key}`,
      input.before
    );
  });

  return ChangeLogStore.of({
    listFacilitatorChanges,
    listScheduleChanges,
    listScheduleChangesBySession,
    logFacilitatorChange,
    logScheduleChange,
  });
});

export const ChangeLogStoreLive = Layer.effect(
  ChangeLogStore,
  makeChangeLogStore
);
