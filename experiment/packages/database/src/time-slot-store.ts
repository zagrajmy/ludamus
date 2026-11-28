import { EventId, TimeSlotId, TimeSlotStore } from "@zagrajmy/core";
import { Effect, Layer, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";

import { decodeInput, decodeOne, decodeRows } from "./rows.js";
import { TimeSlotRow } from "./shared-rows.js";
import { ROW_BUDGET } from "./sql-fragments.js";

const ScopeInput = Schema.Struct({ eventId: EventId, id: TimeSlotId });

export const makeTimeSlotStore = Effect.gen(function* makeTimeSlotStore() {
  const sql = yield* SqlClient;

  const columns = sql.literal(
    "ts.id AS id, ts.event_id AS eventId, ts.start_time AS startTime, ts.end_time AS endTime"
  );

  const listByEvent = Effect.fn("TimeSlotStore.listByEvent")(
    function* listByEvent(eventId: EventId) {
      const valid = yield* decodeInput(
        "TimeSlotStore.listByEvent",
        EventId
      )(eventId);

      return yield* sql`
      SELECT ${columns} FROM time_slot ts WHERE ts.event_id = ${valid}
      ORDER BY ts.start_time, ts.id LIMIT ${ROW_BUDGET.eventTimeSlots}
    `.pipe(decodeRows("TimeSlotStore.listByEvent", TimeSlotRow));
    }
  );

  const readInEvent = Effect.fn("TimeSlotStore.readInEvent")(
    function* readInEvent(scope: typeof ScopeInput.Type) {
      const input = yield* decodeInput(
        "TimeSlotStore.readInEvent",
        ScopeInput
      )(scope);

      return yield* sql`
      SELECT ${columns} FROM time_slot ts WHERE ts.id = ${input.id} AND ts.event_id = ${input.eventId}
    `.pipe(
        decodeOne({
          entity: "TimeSlot",
          key: String(input.id),
          operation: "TimeSlotStore.readInEvent",
          row: TimeSlotRow,
        })
      );
    }
  );

  const idsWithProposals = Effect.fn("TimeSlotStore.idsWithProposals")(
    function* idsWithProposals(eventId: EventId) {
      const valid = yield* decodeInput(
        "TimeSlotStore.idsWithProposals",
        EventId
      )(eventId);

      const rows = yield* sql`
      SELECT DISTINCT ts.id AS id FROM time_slot ts
      JOIN session_time_slots sts ON sts.timeslot_id = ts.id
      JOIN session s ON s.id = sts.session_id AND s.deleted_at IS NULL
      WHERE ts.event_id = ${valid} ORDER BY ts.id LIMIT ${ROW_BUDGET.eventTimeSlots}
    `.pipe(
        decodeRows(
          "TimeSlotStore.idsWithProposals",
          Schema.Struct({ id: TimeSlotId })
        )
      );

      return rows.map((row) => row.id);
    }
  );

  return TimeSlotStore.of({ idsWithProposals, listByEvent, readInEvent });
});

export const TimeSlotStoreLive = Layer.effect(TimeSlotStore, makeTimeSlotStore);
