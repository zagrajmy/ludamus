import { Encounter, EncounterStore, SphereId } from "@zagrajmy/core";
import { Effect, Layer, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";

import { decodeInput, decodeRows, SqlBool, SqlDateTime } from "./rows.js";
import { ROW_BUDGET } from "./sql-fragments.js";

const EncounterRow = Schema.Struct({
  ...Encounter.fields,
  creationTime: SqlDateTime,
  endTime: Schema.NullOr(SqlDateTime),
  isPublic: SqlBool,
  startTime: SqlDateTime,
});

export const makeEncounterStore = Effect.gen(function* makeEncounterStore() {
  const sql = yield* SqlClient;

  const listPublic = Effect.fn("EncounterStore.listPublic")(
    function* listPublic(sphereId: SphereId) {
      const valid = yield* decodeInput(
        "EncounterStore.listPublic",
        SphereId
      )(sphereId);

      return yield* sql`
      SELECT e.id AS id, e.sphere_id AS sphereId, e.creator_id AS creatorId, e.title AS title,
        e.description AS description, e.game AS game, e.start_time AS startTime,
        e.end_time AS endTime, e.place AS place, e.max_participants AS maxParticipants,
        e.is_public AS isPublic, e.share_code AS shareCode, e.header_image AS headerImage,
        e.header_image_original_name AS headerImageOriginalName, e.creation_time AS creationTime,
        (SELECT COUNT(*) FROM encounter_rsvp r WHERE r.encounter_id = e.id) AS rsvpCount
      FROM encounter e WHERE e.sphere_id = ${valid} AND e.is_public = 1
      ORDER BY e.start_time, e.id LIMIT ${ROW_BUDGET.encounters}
    `.pipe(decodeRows("EncounterStore.listPublic", EncounterRow));
    }
  );

  return EncounterStore.of({ listPublic });
});

export const EncounterStoreLive = Layer.effect(
  EncounterStore,
  makeEncounterStore
);
