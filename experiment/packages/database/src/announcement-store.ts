import { Announcement, AnnouncementStore, SphereId } from "@zagrajmy/core";
import { Effect, Layer, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";

import { decodeInput, decodeRows, SqlBool, SqlDateTime } from "./rows.js";
import { ROW_BUDGET } from "./sql-fragments.js";

const AnnouncementRow = Schema.Struct({
  ...Announcement.fields,
  creationTime: SqlDateTime,
  isPublished: SqlBool,
  modificationTime: SqlDateTime,
  notifiedAt: Schema.NullOr(SqlDateTime),
});

export const makeAnnouncementStore = Effect.gen(
  function* makeAnnouncementStore() {
    const sql = yield* SqlClient;

    const listPublished = Effect.fn("AnnouncementStore.listPublished")(
      function* listPublished(sphereId: SphereId) {
        const valid = yield* decodeInput(
          "AnnouncementStore.listPublished",
          SphereId
        )(sphereId);

        return yield* sql`
      SELECT id, sphere_id AS sphereId, title, content, is_published AS isPublished,
        notified_at AS notifiedAt, creation_time AS creationTime, modification_time AS modificationTime
      FROM announcement WHERE sphere_id = ${valid} AND is_published = 1
      ORDER BY creation_time DESC, id DESC LIMIT ${ROW_BUDGET.announcements}
    `.pipe(decodeRows("AnnouncementStore.listPublished", AnnouncementRow));
      }
    );

    return AnnouncementStore.of({ listPublished });
  }
);

export const AnnouncementStoreLive = Layer.effect(
  AnnouncementStore,
  makeAnnouncementStore
);
