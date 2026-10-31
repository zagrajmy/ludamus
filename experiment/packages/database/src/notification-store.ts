import {
  NAVBAR_NOTIFICATION_LIMIT,
  NavbarNotification,
} from "@zagrajmy/core/notification";
import { NotificationStore } from "@zagrajmy/core/ports/notification-store";
import { Effect, Layer, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";

import { decodeFirst, decodeInput, decodeRows, SqlBool } from "./rows.js";

const NotificationRow = Schema.Struct({
  ...NavbarNotification.fields,
  isRead: SqlBool,
});

const CountRow = Schema.Struct({ unread: Schema.Int });

const COLUMNS = `id, title, body, url, (read_at IS NOT NULL) AS isRead`;

const KeyInput = Schema.Struct({ id: Schema.Int, userId: Schema.Int });

export const makeNotificationStore = Effect.gen(
  function* makeNotificationStore() {
    const sql = yield* SqlClient;

    const navbar = Effect.fn("NotificationStore.navbar")(function* navbar(
      userId: number
    ) {
      const operation = "NotificationStore.navbar";
      const id = yield* decodeInput(operation, Schema.Int)(userId);

      const items = yield* sql`SELECT ${sql.literal(COLUMNS)} FROM notification
      WHERE recipient_id = ${id} ORDER BY creation_time DESC, id DESC
      LIMIT ${NAVBAR_NOTIFICATION_LIMIT}`.pipe(
        decodeRows(operation, NotificationRow)
      );

      const [count] = yield* sql`SELECT COUNT(*) AS unread FROM notification
      WHERE recipient_id = ${id} AND read_at IS NULL`.pipe(
        decodeRows(operation, CountRow)
      );

      return { items, unreadCount: count?.unread ?? 0 };
    });

    const readForRecipient = Effect.fn("NotificationStore.readForRecipient")(
      function* readForRecipient(options: typeof KeyInput.Type) {
        const operation = "NotificationStore.readForRecipient";
        const input = yield* decodeInput(operation, KeyInput)(options);

        return yield* sql`SELECT ${sql.literal(COLUMNS)} FROM notification
        WHERE id = ${input.id} AND recipient_id = ${input.userId}`.pipe(
          decodeFirst(operation, NotificationRow)
        );
      }
    );

    return NotificationStore.of({ navbar, readForRecipient });
  }
);

export const NotificationStoreLive = Layer.effect(
  NotificationStore,
  makeNotificationStore
);
