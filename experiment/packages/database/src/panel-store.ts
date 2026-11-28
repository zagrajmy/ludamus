import { SessionId, SphereId, UserId } from "@zagrajmy/core";
import { EventId } from "@zagrajmy/core/ids";
import type { PanelStats } from "@zagrajmy/core/panel/schemas";
import {
  PanelRole,
  ScheduledSession,
  SphereManager,
} from "@zagrajmy/core/panel/schemas";
import { PanelStore } from "@zagrajmy/core/ports/panel-store";
import { DateTime, Effect, Layer, Option, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";

import {
  decodeFirst,
  decodeInput,
  decodeRows,
  pythonJson,
  SqlDateTime,
  storeFailure,
  toSqlDateTime,
} from "./rows.js";
import { ROW_BUDGET } from "./sql-fragments.js";

const SPHERE_MANAGER_BUDGET = 500;

const RoleInput = Schema.Struct({ sphereId: SphereId, userId: UserId });

const RoleRow = Schema.Struct({ role: Schema.String });

const ScheduledRow = Schema.Struct({
  ...ScheduledSession.fields,
  endTime: SqlDateTime,
  startTime: SqlDateTime,
});

const AnnouncementInput = Schema.Struct({
  body: Schema.String,
  recipientIds: Schema.Array(UserId),
  sessionId: SessionId,
  title: Schema.String.check(Schema.isMaxLength(255)),
  url: Schema.String,
});

const StatsRow = Schema.Struct({
  hostsCount: Schema.Int,
  pendingProposals: Schema.Int,
  roomsCount: Schema.Int,
  scheduledSessions: Schema.Int,
  totalProposals: Schema.Int,
});

export const makePanelStore = Effect.gen(function* makePanelStore() {
  const sql = yield* SqlClient;

  const roleOf = Effect.fn("PanelStore.roleOf")(function* roleOf(options: {
    readonly sphereId: SphereId;
    readonly userId: UserId;
  }) {
    const input = yield* decodeInput("PanelStore.roleOf", RoleInput)(options);

    const row = yield* sql`
      SELECT role FROM sphere_managers
      WHERE sphere_id = ${input.sphereId} AND user_id = ${input.userId}
      ORDER BY id LIMIT 1
    `.pipe(decodeFirst("PanelStore.roleOf", RoleRow));

    return row.pipe(
      Option.flatMap(({ role }) => Schema.decodeUnknownOption(PanelRole)(role))
    );
  });

  const eventStats = Effect.fn("PanelStore.eventStats")(function* eventStats(
    eventId: EventId
  ) {
    const id = yield* decodeInput("PanelStore.eventStats", EventId)(eventId);

    const rows = yield* sql`
      SELECT
        (SELECT COUNT(*) FROM session s JOIN proposal_category c ON c.id = s.category_id
          WHERE c.event_id = ${id} AND s.deleted_at IS NULL AND s.status = 'pending') AS pendingProposals,
        (SELECT COUNT(*) FROM session s JOIN proposal_category c ON c.id = s.category_id
          WHERE c.event_id = ${id} AND s.deleted_at IS NULL) AS totalProposals,
        (SELECT COUNT(DISTINCT s.presenter_id) FROM session s
          JOIN proposal_category c ON c.id = s.category_id
          WHERE c.event_id = ${id} AND s.deleted_at IS NULL) AS hostsCount,
        (SELECT COUNT(*) FROM session s
          WHERE s.event_id = ${id} AND s.deleted_at IS NULL
          AND EXISTS (SELECT 1 FROM agenda_item a WHERE a.session_id = s.id)) AS scheduledSessions,
        (SELECT COUNT(*) FROM space WHERE event_id = ${id}) AS roomsCount
    `.pipe(decodeRows("PanelStore.eventStats", StatsRow));

    const stats: PanelStats = rows[0] ?? {
      hostsCount: 0,
      pendingProposals: 0,
      roomsCount: 0,
      scheduledSessions: 0,
      totalProposals: 0,
    };

    return stats;
  });

  const sphereManagers = Effect.fn("PanelStore.sphereManagers")(
    function* sphereManagers(sphereId: SphereId) {
      const id = yield* decodeInput(
        "PanelStore.sphereManagers",
        SphereId
      )(sphereId);

      return yield* sql`
        SELECT u.id AS id,
               CASE WHEN u.name = '' THEN u.username ELSE u.name END AS name
        FROM sphere_managers m JOIN user u ON u.id = m.user_id
        WHERE m.sphere_id = ${id} AND m.role = 'manager'
        ORDER BY u.name, m.id
        LIMIT ${SPHERE_MANAGER_BUDGET}
      `.pipe(decodeRows("PanelStore.sphereManagers", SphereManager));
    }
  );

  const scheduledSessions = Effect.fn("PanelStore.scheduledSessions")(
    function* scheduledSessions(eventId: EventId) {
      const id = yield* decodeInput(
        "PanelStore.scheduledSessions",
        EventId
      )(eventId);

      return yield* sql`
        SELECT s.id AS id, s.title AS title, COALESCE(sp.name, '') AS spaceName,
               a.start_time AS startTime, a.end_time AS endTime
        FROM agenda_item a
        JOIN session s ON s.id = a.session_id
        LEFT JOIN space sp ON sp.id = a.space_id
        WHERE s.event_id = ${id} AND s.deleted_at IS NULL
        ORDER BY a.start_time, s.id
        LIMIT ${ROW_BUDGET.scheduledSessions}
      `.pipe(decodeRows("PanelStore.scheduledSessions", ScheduledRow));
    }
  );

  const announceAcceptance = Effect.fn("PanelStore.announceAcceptance")(
    function* announceAcceptance(options: {
      readonly body: string;
      readonly recipientIds: readonly UserId[];
      readonly sessionId: SessionId;
      readonly title: string;
      readonly url: string;
    }) {
      const input = yield* decodeInput(
        "PanelStore.announceAcceptance",
        AnnouncementInput
      )(options);

      const now = toSqlDateTime(yield* DateTime.now);
      const payload = pythonJson({ session_id: input.sessionId });

      yield* Effect.forEach(
        [...new Set(input.recipientIds)],
        (recipientId) =>
          sql`
            INSERT INTO notification (kind, title, body, url, payload, creation_time, read_at, recipient_id)
            SELECT 'proposal_accepted', ${input.title}, ${input.body}, ${input.url}, ${payload}, ${now}, NULL, ${recipientId}
            WHERE NOT EXISTS (
              SELECT 1 FROM notification
              WHERE recipient_id = ${recipientId} AND kind = 'proposal_accepted'
                AND json_extract(payload, '$.session_id') = ${input.sessionId}
            )
          `,
        { discard: true }
      ).pipe(storeFailure("PanelStore.announceAcceptance"));
    }
  );

  return PanelStore.of({
    announceAcceptance,
    eventStats,
    roleOf,
    scheduledSessions,
    sphereManagers,
  });
});

export const PanelStoreLive = Layer.effect(PanelStore, makePanelStore);
