import {
  Event,
  EventListItem,
  EventProposalSettings,
  EventStore,
  EventSummary,
} from "@zagrajmy/core";
import { DateTime, Effect, Layer, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";

import {
  decodeInput,
  decodeOne,
  decodeRows,
  SqlBool,
  SqlDateTime,
  toSqlDateTime,
} from "./rows.js";
import { PUBLIC_SCHEDULED_SESSION, ROW_BUDGET } from "./sql-fragments.js";

const EventTimeColumns = {
  endTime: SqlDateTime,
  proposalEndTime: Schema.NullOr(SqlDateTime),
  proposalStartTime: Schema.NullOr(SqlDateTime),
  publicationTime: Schema.NullOr(SqlDateTime),
  startTime: SqlDateTime,
};

const EventRow = Schema.Struct({
  ...Event.fields,
  ...EventTimeColumns,
  allowFacilitatorSessionEdit: Schema.NullOr(SqlBool),
  autoConfirmSessions: SqlBool,
  useParticipantsLabel: SqlBool,
  useSessionCoverPlaceholders: SqlBool,
});

const EventListItemRow = Schema.Struct({
  ...EventListItem.fields,
  ...EventTimeColumns,
});

const ProposalSettingsRow = Schema.Struct({
  ...EventProposalSettings.fields,
  allowAnonymousProposals: SqlBool,
});

const FeedInput = Schema.Struct({
  includeHidden: Schema.Boolean,
  now: Schema.DateTimeUtc,
  sphereId: Event.fields.sphereId,
});

const SlugInput = Schema.Struct({
  slug: Schema.String,
  sphereId: Event.fields.sphereId,
});

const InSphereInput = Schema.Struct({
  id: Event.fields.id,
  sphereId: Event.fields.sphereId,
});

const EVENT_COLUMNS = `
  e.id AS id, e.sphere_id AS sphereId, e.name AS name, e.slug AS slug,
  e.description AS description, e.address AS address,
  e.cover_image AS coverImage, e.cover_image_original_name AS coverImageOriginalName,
  e.logo AS logo, e.logo_original_name AS logoOriginalName,
  e.start_time AS startTime, e.end_time AS endTime,
  e.publication_time AS publicationTime,
  e.proposal_start_time AS proposalStartTime, e.proposal_end_time AS proposalEndTime,
  e.visibility AS visibility,
  e.allow_facilitator_session_edit AS allowFacilitatorSessionEdit,
  e.auto_confirm_sessions AS autoConfirmSessions,
  e.use_session_cover_placeholders AS useSessionCoverPlaceholders,
  e.use_participants_label AS useParticipantsLabel,
  COALESCE(ps.description, '') AS proposalDescription`;

export const makeEventStore = Effect.gen(function* makeEventStore() {
  const sql = yield* SqlClient;
  const columns = sql.literal(EVENT_COLUMNS);

  const fromEvent = sql.literal(
    "FROM event e LEFT JOIN event_proposal_settings ps ON ps.event_id = e.id"
  );

  const listPublished = Effect.fn("EventStore.listPublished")(
    function* listPublished(sphereId: EventSummary["sphereId"]) {
      const valid = yield* decodeInput(
        "EventStore.listPublished",
        EventSummary.fields.sphereId
      )(sphereId);

      const now = toSqlDateTime(yield* DateTime.now);

      return yield* sql`
      SELECT id, name, slug, sphere_id AS sphereId,
             start_time AS startTime, end_time AS endTime
      FROM event
      WHERE sphere_id = ${valid}
        AND publication_time IS NOT NULL
        AND publication_time <= ${now}
        AND visibility = 'public'
      ORDER BY start_time ASC
      LIMIT ${ROW_BUDGET.feedEvents}
    `.pipe(decodeRows("EventStore.listPublished", EventSummary));
    }
  );

  const listForFeed = Effect.fn("EventStore.listForFeed")(function* listForFeed(
    options: typeof FeedInput.Type
  ) {
    const input = yield* decodeInput(
      "EventStore.listForFeed",
      FeedInput
    )(options);

    const listed = input.includeHidden
      ? sql`1 = 1`
      : sql`e.publication_time IS NOT NULL AND e.publication_time <= ${toSqlDateTime(input.now)} AND e.visibility = 'public'`;

    return yield* sql`
      SELECT e.id AS id, e.name AS name, e.slug AS slug, e.description AS description,
             e.cover_image AS coverImage, e.start_time AS startTime, e.end_time AS endTime,
             e.publication_time AS publicationTime,
             e.proposal_start_time AS proposalStartTime,
             e.proposal_end_time AS proposalEndTime, e.visibility AS visibility,
             (SELECT COUNT(*) FROM session s
              WHERE s.event_id = e.id AND ${sql.literal(PUBLIC_SCHEDULED_SESSION)}) AS sessionCount
      FROM event e
      WHERE e.sphere_id = ${input.sphereId} AND ${listed}
      ORDER BY e.start_time ASC, e.id ASC
      LIMIT ${ROW_BUDGET.feedEvents}
    `.pipe(decodeRows("EventStore.listForFeed", EventListItemRow));
  });

  const listBySphere = Effect.fn("EventStore.listBySphere")(
    function* listBySphere(sphereId: Event["sphereId"]) {
      const valid = yield* decodeInput(
        "EventStore.listBySphere",
        Event.fields.sphereId
      )(sphereId);

      return yield* sql`
      SELECT ${columns} ${fromEvent}
      WHERE e.sphere_id = ${valid}
      ORDER BY e.start_time DESC, e.id DESC
      LIMIT ${ROW_BUDGET.sphereEvents}
    `.pipe(decodeRows("EventStore.listBySphere", EventRow));
    }
  );

  const read = Effect.fn("EventStore.read")(function* read(id: Event["id"]) {
    const valid = yield* decodeInput("EventStore.read", Event.fields.id)(id);

    return yield* sql`SELECT ${columns} ${fromEvent} WHERE e.id = ${valid}`.pipe(
      decodeOne({
        entity: "Event",
        key: String(valid),
        operation: "EventStore.read",
        row: EventRow,
      })
    );
  });

  const readInSphere = Effect.fn("EventStore.readInSphere")(
    function* readInSphere(options: typeof InSphereInput.Type) {
      const input = yield* decodeInput(
        "EventStore.readInSphere",
        InSphereInput
      )(options);

      return yield* sql`
      SELECT ${columns} ${fromEvent} WHERE e.id = ${input.id} AND e.sphere_id = ${input.sphereId}
    `.pipe(
        decodeOne({
          entity: "Event",
          key: String(input.id),
          operation: "EventStore.readInSphere",
          row: EventRow,
        })
      );
    }
  );

  const readBySlug = Effect.fn("EventStore.readBySlug")(function* readBySlug(
    options: typeof SlugInput.Type
  ) {
    const input = yield* decodeInput(
      "EventStore.readBySlug",
      SlugInput
    )(options);

    return yield* sql`
      SELECT ${columns} ${fromEvent} WHERE e.slug = ${input.slug} AND e.sphere_id = ${input.sphereId}
    `.pipe(
      decodeOne({
        entity: "Event",
        key: input.slug,
        operation: "EventStore.readBySlug",
        row: EventRow,
      })
    );
  });

  const readProposalSettings = Effect.fn("EventStore.readProposalSettings")(
    function* readProposalSettings(eventId: Event["id"]) {
      const valid = yield* decodeInput(
        "EventStore.readProposalSettings",
        Event.fields.id
      )(eventId);

      return yield* sql`
        SELECT COALESCE(MAX(ps.id), 0) AS id,
               COALESCE(MAX(ps.allow_anonymous_proposals), 0) AS allowAnonymousProposals,
               COALESCE(MAX(ps.description), '') AS description
        FROM event_proposal_settings ps WHERE ps.event_id = ${valid}
      `.pipe(
        decodeOne({
          entity: "EventProposalSettings",
          key: String(valid),
          operation: "EventStore.readProposalSettings",
          row: ProposalSettingsRow,
        }),
        Effect.catchTag("NotFound", () =>
          Effect.succeed({
            allowAnonymousProposals: false,
            description: "",
            id: 0,
          })
        )
      );
    }
  );

  return EventStore.of({
    listBySphere,
    listForFeed,
    listPublished,
    read,
    readBySlug,
    readInSphere,
    readProposalSettings,
  });
});

export const EventStoreLive = Layer.effect(EventStore, makeEventStore);
