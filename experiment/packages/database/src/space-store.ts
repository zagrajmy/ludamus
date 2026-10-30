import { EventId, Space, SpaceId, SpaceStore } from "@zagrajmy/core";
import type { Location } from "@zagrajmy/core";
import { Effect, Layer, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";

import { decodeInput, decodeOne, decodeRows, SqlDateTime } from "./rows.js";
import { LocationRow } from "./shared-rows.js";
import { ROW_BUDGET } from "./sql-fragments.js";

const SpaceRow = Schema.Struct({
  ...Space.fields,
  creationTime: SqlDateTime,
  modificationTime: SqlDateTime,
});

const SPACE_COLUMNS = `
  sp.id AS id, sp.event_id AS eventId, sp.parent_id AS parentId, sp.name AS name,
  sp.slug AS slug, sp.capacity AS capacity, sp.description AS description,
  sp.location AS location, sp."order" AS "order", sp.programme_order AS programmeOrder,
  sp.creation_time AS creationTime, sp.modification_time AS modificationTime`;

const LocatedRow = Schema.Struct({ ...LocationRow.fields, leafId: SpaceId });

const ScopeInput = Schema.Struct({ eventId: EventId, id: SpaceId });

export const locationsQuery = (sql: SqlClient, eventId: EventId) => sql`
  WITH RECURSIVE chain(leafId, id, parentId, name, ord, depth) AS (
    SELECT id, id, parent_id, name, "order", 0 FROM space WHERE event_id = ${eventId}
    UNION ALL
    SELECT chain.leafId, p.id, p.parent_id, p.name, p."order", chain.depth + 1
    FROM chain JOIN space p ON p.id = chain.parentId
    WHERE p.event_id = ${eventId} AND chain.depth < 7
  )
  SELECT leaf.id AS leafId, leaf.id AS spaceId, COALESCE(leaf.parent_id, 0) AS parentId,
    leaf.name AS spaceName, COALESCE(parent.name, '') AS parentName,
    leaf.programme_order AS programmeOrder,
    (SELECT group_concat(chain.name, ' > ' ORDER BY chain.depth DESC)
     FROM chain WHERE chain.leafId = leaf.id) AS path,
    (SELECT json_group_array(json_object('id', chain.id, 'name', chain.name, 'order', chain.ord)
       ORDER BY chain.depth DESC)
     FROM chain WHERE chain.leafId = leaf.id) AS sortPath
  FROM space leaf LEFT JOIN space parent ON parent.id = leaf.parent_id AND parent.event_id = leaf.event_id
  WHERE leaf.event_id = ${eventId}
  ORDER BY leaf.id
  LIMIT ${ROW_BUDGET.eventSpaces}`;

export const makeSpaceStore = Effect.gen(function* makeSpaceStore() {
  const sql = yield* SqlClient;
  const columns = sql.literal(SPACE_COLUMNS);

  const listByEvent = Effect.fn("SpaceStore.listByEvent")(function* listByEvent(
    eventId: EventId
  ) {
    const valid = yield* decodeInput(
      "SpaceStore.listByEvent",
      EventId
    )(eventId);

    return yield* sql`
      SELECT ${columns} FROM space sp WHERE sp.event_id = ${valid}
      ORDER BY sp."order", sp.name, sp.id LIMIT ${ROW_BUDGET.eventSpaces}
    `.pipe(decodeRows("SpaceStore.listByEvent", SpaceRow));
  });

  const readInEvent = Effect.fn("SpaceStore.readInEvent")(function* readInEvent(
    scope: typeof ScopeInput.Type
  ) {
    const input = yield* decodeInput(
      "SpaceStore.readInEvent",
      ScopeInput
    )(scope);

    return yield* sql`
      SELECT ${columns} FROM space sp WHERE sp.id = ${input.id} AND sp.event_id = ${input.eventId}
    `.pipe(
      decodeOne({
        entity: "Space",
        key: String(input.id),
        operation: "SpaceStore.readInEvent",
        row: SpaceRow,
      })
    );
  });

  const locationsByEvent = Effect.fn("SpaceStore.locationsByEvent")(
    function* locationsByEvent(eventId: EventId) {
      const valid = yield* decodeInput(
        "SpaceStore.locationsByEvent",
        EventId
      )(eventId);

      const rows = yield* locationsQuery(sql, valid).pipe(
        decodeRows("SpaceStore.locationsByEvent", LocatedRow)
      );

      return new Map<SpaceId, Location>(
        rows.map(({ leafId, ...location }) => [leafId, location])
      );
    }
  );

  return SpaceStore.of({ listByEvent, locationsByEvent, readInEvent });
});

export const SpaceStoreLive = Layer.effect(SpaceStore, makeSpaceStore);
