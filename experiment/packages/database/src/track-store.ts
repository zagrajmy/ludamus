import {
  DuplicateName,
  EventId,
  SpaceId,
  StoreError,
  Track,
  TrackId,
  TrackListItem,
  TrackStore,
  TrackWrite,
  UserId,
} from "@zagrajmy/core";
import { DateTime, Effect, Layer, Option, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";
import { UniqueViolation } from "effect/sql/SqlError";
import type { SqlError } from "effect/sql/SqlError";

import {
  decodeFirst,
  decodeInput,
  decodeOne,
  decodeRows,
  requireRow,
  SqlBool,
  SqlDateTime,
  storeFailure,
  toSqlDateTime,
} from "./rows.js";
import { ROW_BUDGET } from "./sql-fragments.js";

const TrackRow = Schema.Struct({
  ...Track.fields,
  creationTime: SqlDateTime,
  isPublic: SqlBool,
  modificationTime: SqlDateTime,
});

const AssignmentRow = Schema.Struct({
  id: TrackId,
  isPublic: SqlBool,
  managerNames: Schema.fromJsonString(TrackListItem.fields.managerNames),
  name: Schema.String,
  slug: Schema.String,
  spaceNames: Schema.fromJsonString(TrackListItem.fields.spaceNames),
});

const TRACK_COLUMNS = `
  t.id AS id, t.event_id AS eventId, t.name AS name, t.slug AS slug,
  t.is_public AS isPublic, t.creation_time AS creationTime,
  t.modification_time AS modificationTime`;

const ManagerInput = Schema.Struct({
  eventId: Schema.NullOr(EventId),
  userId: UserId,
});

const SlugInput = Schema.Struct({ eventId: EventId, slug: Schema.String });

const ScopeInput = Schema.Struct({ eventId: EventId, id: TrackId });

const NameInput = Schema.Struct({ eventId: EventId, name: Schema.String });

const SlugExistsInput = Schema.Struct({
  eventId: EventId,
  excludeId: Schema.NullOr(TrackId),
  slug: Schema.String,
});

const CreateInput = Schema.Struct({ eventId: EventId, track: TrackWrite });

const UpdateInput = Schema.Struct({
  eventId: EventId,
  id: TrackId,
  track: TrackWrite,
});

const isNameConflict = (error: SqlError) =>
  error.reason instanceof UniqueViolation &&
  error.reason.constraint.includes("track_unique_name_per_event");

const writeFailure =
  (operation: string, name: string) =>
  (error: SqlError): Effect.Effect<never, DuplicateName | StoreError> =>
    isNameConflict(error)
      ? Effect.fail(new DuplicateName({ entity: "Track", name }))
      : storeFailure(operation)(Effect.fail(error));

export const makeTrackStore = Effect.gen(function* makeTrackStore() {
  const sql = yield* SqlClient;
  const columns = sql.literal(TRACK_COLUMNS);

  const listWhere = (operation: string, where: ReturnType<typeof sql.and>) =>
    sql`SELECT ${columns} FROM track t WHERE ${where} ORDER BY t.name, t.id LIMIT ${ROW_BUDGET.eventTracks}`.pipe(
      decodeRows(operation, TrackRow)
    );

  const listByEvent = Effect.fn("TrackStore.listByEvent")(function* listByEvent(
    eventId: EventId
  ) {
    const valid = yield* decodeInput(
      "TrackStore.listByEvent",
      EventId
    )(eventId);

    return yield* listWhere(
      "TrackStore.listByEvent",
      sql.and([sql`t.event_id = ${valid}`])
    );
  });

  const listPublicByEvent = Effect.fn("TrackStore.listPublicByEvent")(
    function* listPublicByEvent(eventId: EventId) {
      const valid = yield* decodeInput(
        "TrackStore.listPublicByEvent",
        EventId
      )(eventId);

      return yield* listWhere(
        "TrackStore.listPublicByEvent",
        sql.and([sql`t.event_id = ${valid}`, sql`t.is_public = 1`])
      );
    }
  );

  const listByManager = Effect.fn("TrackStore.listByManager")(
    function* listByManager(options: typeof ManagerInput.Type) {
      const input = yield* decodeInput(
        "TrackStore.listByManager",
        ManagerInput
      )(options);

      return yield* listWhere(
        "TrackStore.listByManager",
        sql.and([
          sql`t.id IN (SELECT track_id FROM track_managers WHERE user_id = ${input.userId})`,
          input.eventId === null
            ? sql`1 = 1`
            : sql`t.event_id = ${input.eventId}`,
        ])
      );
    }
  );

  const listWithAssignments = Effect.fn("TrackStore.listWithAssignments")(
    function* listWithAssignments(eventId: EventId) {
      const valid = yield* decodeInput(
        "TrackStore.listWithAssignments",
        EventId
      )(eventId);

      return yield* sql`
      SELECT t.id AS id, t.name AS name, t.slug AS slug, t.is_public AS isPublic,
        (SELECT json_group_array(sp.name ORDER BY sp.name) FROM track_spaces ts
         JOIN space sp ON sp.id = ts.space_id WHERE ts.track_id = t.id) AS spaceNames,
        (SELECT json_group_array(u.name ORDER BY u.name) FROM track_managers tm
         JOIN user u ON u.id = tm.user_id WHERE tm.track_id = t.id) AS managerNames
      FROM track t WHERE t.event_id = ${valid}
      ORDER BY t.name, t.id LIMIT ${ROW_BUDGET.eventTracks}
    `.pipe(decodeRows("TrackStore.listWithAssignments", AssignmentRow));
    }
  );

  const readBySlug = Effect.fn("TrackStore.readBySlug")(function* readBySlug(
    options: typeof SlugInput.Type
  ) {
    const input = yield* decodeInput(
      "TrackStore.readBySlug",
      SlugInput
    )(options);

    return yield* sql`SELECT ${columns} FROM track t WHERE t.event_id = ${input.eventId} AND t.slug = ${input.slug}`.pipe(
      decodeOne({
        entity: "Track",
        key: input.slug,
        operation: "TrackStore.readBySlug",
        row: TrackRow,
      })
    );
  });

  const readInEvent = Effect.fn("TrackStore.readInEvent")(function* readInEvent(
    scope: typeof ScopeInput.Type
  ) {
    const input = yield* decodeInput(
      "TrackStore.readInEvent",
      ScopeInput
    )(scope);

    return yield* sql`SELECT ${columns} FROM track t WHERE t.event_id = ${input.eventId} AND t.id = ${input.id}`.pipe(
      decodeOne({
        entity: "Track",
        key: String(input.id),
        operation: "TrackStore.readInEvent",
        row: TrackRow,
      })
    );
  });

  const findByName = Effect.fn("TrackStore.findByName")(function* findByName(
    options: typeof NameInput.Type
  ) {
    const input = yield* decodeInput(
      "TrackStore.findByName",
      NameInput
    )(options);

    return yield* sql`
      SELECT ${columns} FROM track t WHERE t.event_id = ${input.eventId} AND LOWER(t.name) = LOWER(${input.name}) LIMIT 1
    `.pipe(decodeFirst("TrackStore.findByName", TrackRow));
  });

  const slugExists = Effect.fn("TrackStore.slugExists")(function* slugExists(
    options: typeof SlugExistsInput.Type
  ) {
    const input = yield* decodeInput(
      "TrackStore.slugExists",
      SlugExistsInput
    )(options);

    const excluded =
      input.excludeId === null ? sql`1 = 1` : sql`t.id <> ${input.excludeId}`;

    const rows = yield* sql`
      SELECT t.id AS id FROM track t WHERE t.event_id = ${input.eventId} AND t.slug = ${input.slug} AND ${excluded} LIMIT 1
    `.pipe(decodeRows("TrackStore.slugExists", Schema.Struct({ id: TrackId })));

    return rows.length > 0;
  });

  const spaceIds = Effect.fn("TrackStore.spaceIds")(function* spaceIds(
    trackId: TrackId
  ) {
    const valid = yield* decodeInput("TrackStore.spaceIds", TrackId)(trackId);

    const rows = yield* sql`
      SELECT space_id AS id FROM track_spaces WHERE track_id = ${valid} ORDER BY space_id LIMIT ${ROW_BUDGET.eventSpaces}
    `.pipe(decodeRows("TrackStore.spaceIds", Schema.Struct({ id: SpaceId })));

    return rows.map((row) => row.id);
  });

  const managerIds = Effect.fn("TrackStore.managerIds")(function* managerIds(
    trackId: TrackId
  ) {
    const valid = yield* decodeInput("TrackStore.managerIds", TrackId)(trackId);

    const rows = yield* sql`
      SELECT user_id AS id FROM track_managers WHERE track_id = ${valid} ORDER BY user_id LIMIT ${ROW_BUDGET.eventTracks}
    `.pipe(decodeRows("TrackStore.managerIds", Schema.Struct({ id: UserId })));

    return rows.map((row) => row.id);
  });

  const replaceAssignments = Effect.fn("TrackStore.replaceAssignments")(
    function* replaceAssignments(options: {
      readonly eventId: EventId;
      readonly trackId: TrackId;
      readonly track: TrackWrite;
    }) {
      yield* sql`DELETE FROM track_spaces WHERE track_id = ${options.trackId}`;
      yield* sql`DELETE FROM track_managers WHERE track_id = ${options.trackId}`;
      const spaces = [...new Set(options.track.spaceIds)];
      const managers = [...new Set(options.track.managerIds)];

      if (spaces.length > 0) {
        yield* sql`
        INSERT INTO track_spaces (track_id, space_id)
        SELECT ${options.trackId}, sp.id FROM space sp WHERE sp.event_id = ${options.eventId} AND ${sql.in("sp.id", spaces)}
      `;
      }

      if (managers.length > 0) {
        yield* sql`INSERT INTO track_managers ${sql.insert(managers.map((user_id) => ({ track_id: options.trackId, user_id })))}`;
      }
    }
  );

  const create = Effect.fn("TrackStore.create")(function* create(
    options: typeof CreateInput.Type
  ) {
    const input = yield* decodeInput("TrackStore.create", CreateInput)(options);
    const now = toSqlDateTime(yield* DateTime.now);

    return yield* Effect.gen(function* insertTrack() {
      const rows = yield* sql`
        INSERT INTO track ${sql.insert({
          creation_time: now,
          event_id: input.eventId,
          is_public: input.track.isPublic ? 1 : 0,
          modification_time: now,
          name: input.track.name,
          slug: input.track.slug,
        })} RETURNING id
      `;

      const id = yield* Schema.decodeUnknownEffect(
        Schema.Array(Schema.Struct({ id: TrackId }))
      )(rows).pipe(
        Effect.flatMap((decoded) =>
          Option.match(Option.fromNullishOr(decoded[0]), {
            onNone: () =>
              Effect.fail(
                new StoreError({
                  operation: "TrackStore.create",
                  reason: "insert returned no id",
                })
              ),
            onSome: (row) => Effect.succeed(row.id),
          })
        ),
        Effect.catchTag("SchemaError", () =>
          Effect.fail(
            new StoreError({
              operation: "TrackStore.create",
              reason: "SchemaError",
            })
          )
        )
      );

      yield* replaceAssignments({
        eventId: input.eventId,
        track: input.track,
        trackId: id,
      });

      return yield* sql`SELECT ${columns} FROM track t WHERE t.id = ${id}`.pipe(
        decodeOne({
          entity: "Track",
          key: String(id),
          operation: "TrackStore.create",
          row: TrackRow,
        })
      );
    }).pipe(
      sql.withTransaction,
      Effect.catchTag(
        "SqlError",
        writeFailure("TrackStore.create", input.track.name)
      ),
      Effect.catchTag("NotFound", () =>
        Effect.fail(
          new StoreError({
            operation: "TrackStore.create",
            reason: "inserted row vanished",
          })
        )
      )
    );
  });

  const update = Effect.fn("TrackStore.update")(function* update(
    options: typeof UpdateInput.Type
  ) {
    const input = yield* decodeInput("TrackStore.update", UpdateInput)(options);
    const now = toSqlDateTime(yield* DateTime.now);

    return yield* Effect.gen(function* updateTrack() {
      const current =
        yield* sql`SELECT ${columns} FROM track t WHERE t.id = ${input.id} AND t.event_id = ${input.eventId}`.pipe(
          decodeOne({
            entity: "Track",
            key: String(input.id),
            operation: "TrackStore.update",
            row: TrackRow,
          })
        );

      if (
        current.name !== input.track.name ||
        current.isPublic !== input.track.isPublic ||
        current.slug !== input.track.slug
      ) {
        yield* sql`
          UPDATE track SET ${sql.update({
            is_public: input.track.isPublic ? 1 : 0,
            modification_time: now,
            name: input.track.name,
            slug: input.track.slug,
          })} WHERE id = ${input.id}
        `;
      }

      yield* replaceAssignments({
        eventId: input.eventId,
        track: input.track,
        trackId: input.id,
      });

      return yield* sql`SELECT ${columns} FROM track t WHERE t.id = ${input.id}`.pipe(
        decodeOne({
          entity: "Track",
          key: String(input.id),
          operation: "TrackStore.update",
          row: TrackRow,
        })
      );
    }).pipe(
      sql.withTransaction,
      Effect.catchTag(
        "SqlError",
        writeFailure("TrackStore.update", input.track.name)
      )
    );
  });

  const remove = Effect.fn("TrackStore.delete")(function* remove(
    scope: typeof ScopeInput.Type
  ) {
    const input = yield* decodeInput("TrackStore.delete", ScopeInput)(scope);

    const rows = yield* Effect.gen(function* deleteTrack() {
      yield* sql`DELETE FROM session_tracks WHERE track_id IN (SELECT id FROM track WHERE id = ${input.id} AND event_id = ${input.eventId})`;
      yield* sql`DELETE FROM track_spaces WHERE track_id IN (SELECT id FROM track WHERE id = ${input.id} AND event_id = ${input.eventId})`;
      yield* sql`DELETE FROM track_managers WHERE track_id IN (SELECT id FROM track WHERE id = ${input.id} AND event_id = ${input.eventId})`;

      return yield* sql`DELETE FROM track WHERE id = ${input.id} AND event_id = ${input.eventId} RETURNING id`;
    }).pipe(sql.withTransaction, storeFailure("TrackStore.delete"));

    yield* requireRow({ entity: "Track", key: String(input.id) })(
      rows.map(() => ({ id: input.id }))
    );
  });

  return TrackStore.of({
    create,
    delete: remove,
    findByName,
    listByEvent,
    listByManager,
    listPublicByEvent,
    listWithAssignments,
    managerIds,
    readBySlug,
    readInEvent,
    slugExists,
    spaceIds,
    update,
  });
});

export const TrackStoreLive = Layer.effect(TrackStore, makeTrackStore);
