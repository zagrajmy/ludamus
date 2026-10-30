import { EventStore, EventSummary } from "@zagrajmy/core";
import { Effect, Layer } from "effect";
import { SqlClient } from "effect/sql/SqlClient";

import { decodeRows } from "./rows.js";

export const EventStoreLive = Layer.effect(
  EventStore,
  Effect.gen(function* makeEventStore() {
    const sql = yield* SqlClient;

    return EventStore.of({
      listPublished: (sphereId) =>
        sql`
          SELECT id, name, slug, sphere_id AS sphereId,
                 start_time AS startTime, end_time AS endTime
          FROM event
          WHERE sphere_id = ${sphereId}
            AND publication_time IS NOT NULL
            AND visibility = 'public'
          ORDER BY start_time ASC
        `.pipe(decodeRows("EventStore.listPublished", EventSummary)),
    });
  })
);
