import {
  AccreditationType,
  EventId,
  FacilitatorChanges,
  FacilitatorId,
  FacilitatorListFilters,
  FacilitatorListItem,
  FacilitatorSessionCounts,
  FacilitatorStore,
  NewFacilitator,
  StoreError,
  UserId,
} from "@zagrajmy/core";
import { DateTime, Effect, Layer, Option, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";
import type { Fragment } from "effect/sql/Statement";

import {
  decodeFirst,
  decodeInput,
  decodeOne,
  decodeRows,
  IdRow,
  likeContains,
  pythonJson,
  requireRow,
  SqlDateTime,
  toSqlDateTime,
} from "./rows.js";
import { FACILITATOR_COLUMNS, FacilitatorRow } from "./shared-rows.js";
import { ROW_BUDGET } from "./sql-fragments.js";

const ListItemRow = Schema.Struct({
  ...FacilitatorListItem.fields,
  deletedAt: Schema.NullOr(SqlDateTime),
});

const ScopeInput = Schema.Struct({ eventId: EventId, id: FacilitatorId });

const SlugInput = Schema.Struct({ eventId: EventId, slug: Schema.String });

const UserInput = Schema.Struct({ eventId: EventId, userId: UserId });

const NameInput = Schema.Struct({
  displayName: Schema.String,
  eventId: EventId,
});

const ListInput = Schema.Struct({
  eventId: EventId,
  filters: FacilitatorListFilters,
});

const UpdateInput = Schema.Struct({
  changes: FacilitatorChanges,
  eventId: EventId,
  id: FacilitatorId,
});

const AccreditationInput = Schema.Struct({
  accreditationType: AccreditationType,
  eventId: EventId,
  ids: Schema.Array(FacilitatorId),
});

const ClaimInput = Schema.Struct({
  eventId: EventId,
  id: FacilitatorId,
  organizerId: UserId,
});

const ReleaseInput = Schema.Struct({
  eventId: EventId,
  id: FacilitatorId,
  organizerId: Schema.NullOr(UserId),
});

const SORT_COLUMNS = new Map<string, string>([
  ["accreditation", "f.accreditation_type"],
  ["linked", "f.user_id"],
  ["name", "f.display_name"],
  ["organizer", "o.name"],
  ["sessions", "sessionCount"],
]);

const LIVE_SESSION_COUNT = `(
  SELECT COUNT(DISTINCT sf.session_id) FROM session_facilitators sf
  JOIN session ls ON ls.id = sf.session_id
  WHERE sf.facilitator_id = f.id AND ls.deleted_at IS NULL)`;

export const makeFacilitatorStore = Effect.gen(
  function* makeFacilitatorStore() {
    const sql = yield* SqlClient;
    const columns = sql.literal(FACILITATOR_COLUMNS);

    const from = sql.literal(
      "FROM facilitator f LEFT JOIN user o ON o.id = f.organizer_id"
    );

    const readWhere = (operation: string, key: string, where: Fragment) =>
      sql`SELECT ${columns} ${from} WHERE ${where}`.pipe(
        decodeOne({
          entity: "Facilitator",
          key,
          operation,
          row: FacilitatorRow,
        })
      );

    const create = Effect.fn("FacilitatorStore.create")(function* create(
      facilitator: typeof NewFacilitator.Type
    ) {
      const input = yield* decodeInput(
        "FacilitatorStore.create",
        NewFacilitator
      )(facilitator);

      const rows = yield* sql`
      INSERT INTO facilitator ${sql.insert({
        accreditation_type: input.accreditationType,
        deleted_at: null,
        display_name: input.displayName,
        event_id: input.eventId,
        guild_id: null,
        ident: input.ident,
        internal_comment: "",
        is_collective: input.isCollective ? 1 : 0,
        organizer_id: input.organizerId,
        slug: input.slug,
        user_id: input.userId,
      })} RETURNING id
    `.pipe(decodeRows("FacilitatorStore.create", IdRow));

      const id = rows[0]?.id;

      if (id === undefined) {
        return yield* new StoreError({
          operation: "FacilitatorStore.create",
          reason: "insert returned no id",
        });
      }

      return yield* readWhere(
        "FacilitatorStore.create",
        String(id),
        sql`f.id = ${id}`
      ).pipe(
        Effect.catchTag("NotFound", () =>
          Effect.fail(
            new StoreError({
              operation: "FacilitatorStore.create",
              reason: "inserted row vanished",
            })
          )
        )
      );
    });

    const readInEvent = Effect.fn("FacilitatorStore.readInEvent")(
      function* readInEvent(scope: typeof ScopeInput.Type) {
        const input = yield* decodeInput(
          "FacilitatorStore.readInEvent",
          ScopeInput
        )(scope);

        return yield* readWhere(
          "FacilitatorStore.readInEvent",
          String(input.id),
          sql`f.id = ${input.id} AND f.event_id = ${input.eventId} AND f.deleted_at IS NULL`
        );
      }
    );

    const readBySlug = Effect.fn("FacilitatorStore.readBySlug")(
      function* readBySlug(options: typeof SlugInput.Type) {
        const input = yield* decodeInput(
          "FacilitatorStore.readBySlug",
          SlugInput
        )(options);

        return yield* readWhere(
          "FacilitatorStore.readBySlug",
          input.slug,
          sql`f.event_id = ${input.eventId} AND f.slug = ${input.slug} AND f.deleted_at IS NULL`
        );
      }
    );

    const readBySlugIncludingDeleted = Effect.fn(
      "FacilitatorStore.readBySlugIncludingDeleted"
    )(function* readBySlugIncludingDeleted(options: typeof SlugInput.Type) {
      const input = yield* decodeInput(
        "FacilitatorStore.readBySlugIncludingDeleted",
        SlugInput
      )(options);

      return yield* readWhere(
        "FacilitatorStore.readBySlugIncludingDeleted",
        input.slug,
        sql`f.event_id = ${input.eventId} AND f.slug = ${input.slug}`
      );
    });

    const findByUser = Effect.fn("FacilitatorStore.findByUser")(
      function* findByUser(options: typeof UserInput.Type) {
        const input = yield* decodeInput(
          "FacilitatorStore.findByUser",
          UserInput
        )(options);

        return yield* sql`
      SELECT ${columns} ${from}
      WHERE f.event_id = ${input.eventId} AND f.user_id = ${input.userId} AND f.deleted_at IS NULL
      ORDER BY f.id LIMIT 1
    `.pipe(decodeFirst("FacilitatorStore.findByUser", FacilitatorRow));
      }
    );

    const findByDisplayName = Effect.fn("FacilitatorStore.findByDisplayName")(
      function* findByDisplayName(options: typeof NameInput.Type) {
        const input = yield* decodeInput(
          "FacilitatorStore.findByDisplayName",
          NameInput
        )(options);

        return yield* sql`
      SELECT ${columns} ${from}
      WHERE f.event_id = ${input.eventId} AND f.display_name = ${input.displayName} AND f.deleted_at IS NULL
      ORDER BY f.id LIMIT 1
    `.pipe(decodeFirst("FacilitatorStore.findByDisplayName", FacilitatorRow));
      }
    );

    const slugExists = Effect.fn("FacilitatorStore.slugExists")(
      function* slugExists(options: typeof SlugInput.Type) {
        const input = yield* decodeInput(
          "FacilitatorStore.slugExists",
          SlugInput
        )(options);

        const rows = yield* sql`
      SELECT id FROM facilitator WHERE event_id = ${input.eventId} AND slug = ${input.slug} LIMIT 1
    `.pipe(decodeRows("FacilitatorStore.slugExists", IdRow));

        return rows.length > 0;
      }
    );

    const listItems = (options: {
      readonly operation: string;
      readonly where: Fragment;
      readonly order: Fragment;
      readonly limit: number;
    }) =>
      sql`
      SELECT f.id AS id, f.display_name AS displayName, f.slug AS slug,
        f.accreditation_type AS accreditationType, f.user_id AS userId,
        f.organizer_id AS organizerId, o.name AS organizerName,
        f.deleted_at AS deletedAt, ${sql.literal(LIVE_SESSION_COUNT)} AS sessionCount
      ${from}
      WHERE ${options.where}
      ORDER BY ${options.order}
      LIMIT ${options.limit}
    `.pipe(decodeRows(options.operation, ListItemRow));

    const listByEvent = Effect.fn("FacilitatorStore.listByEvent")(
      function* listByEvent(options: typeof ListInput.Type) {
        const input = yield* decodeInput(
          "FacilitatorStore.listByEvent",
          ListInput
        )(options);

        const { filters } = input;

        const clauses: Fragment[] = [
          sql`f.event_id = ${input.eventId}`,
          sql`f.deleted_at IS NULL`,
        ];

        if (filters.ids !== undefined && filters.ids.length > 0) {
          clauses.push(sql.in("f.id", filters.ids));
        }

        if (filters.search !== undefined && filters.search !== "") {
          const raw = likeContains(filters.search);
          const encoded = likeContains(pythonJson(filters.search).slice(1, -1));
          clauses.push(sql`(
        f.display_name LIKE ${raw} ESCAPE '\\'
        OR EXISTS (SELECT 1 FROM user fu WHERE fu.id = f.user_id AND fu.name LIKE ${raw} ESCAPE '\\')
        OR EXISTS (SELECT 1 FROM personal_data_field_value pv JOIN personal_data_field pf ON pf.id = pv.field_id
          WHERE pv.facilitator_id = f.id AND pf.field_type IN ('text', 'discord')
          AND (pv.value LIKE ${raw} ESCAPE '\\' OR pv.value LIKE ${encoded} ESCAPE '\\')))`);
        }

        if (filters.accreditation !== undefined) {
          clauses.push(sql`f.accreditation_type = ${filters.accreditation}`);
        }

        if (filters.organizerUnassigned === true) {
          clauses.push(sql`f.organizer_id IS NULL`);
        } else if (filters.organizerId !== undefined) {
          clauses.push(sql`f.organizer_id = ${filters.organizerId}`);
        }

        const sort = filters.sort ?? "name";
        const key = sort.startsWith("-") ? sort.slice(1) : sort;
        const direction = sql.literal(sort.startsWith("-") ? "DESC" : "ASC");
        const column = SORT_COLUMNS.get(key) ?? "f.display_name";

        const limit = Math.min(
          filters.limit ?? ROW_BUDGET.panelFacilitators,
          ROW_BUDGET.panelFacilitators
        );

        return yield* listItems({
          limit,
          operation: "FacilitatorStore.listByEvent",
          order: sql`${sql.literal(column)} ${direction}, f.display_name, f.id`,
          where: sql.and(clauses),
        });
      }
    );

    const listDeletedByEvent = Effect.fn("FacilitatorStore.listDeletedByEvent")(
      function* listDeletedByEvent(eventId: EventId) {
        const valid = yield* decodeInput(
          "FacilitatorStore.listDeletedByEvent",
          EventId
        )(eventId);

        return yield* listItems({
          limit: ROW_BUDGET.panelFacilitators,
          operation: "FacilitatorStore.listDeletedByEvent",
          order: sql`f.deleted_at DESC, f.display_name, f.id`,
          where: sql`f.event_id = ${valid} AND f.deleted_at IS NOT NULL`,
        });
      }
    );

    const update = Effect.fn("FacilitatorStore.update")(function* update(
      options: typeof UpdateInput.Type
    ) {
      const input = yield* decodeInput(
        "FacilitatorStore.update",
        UpdateInput
      )(options);

      const { changes } = input;
      const columnValues: Record<string, string | number | null> = {};

      if (changes.accreditationType !== undefined) {
        columnValues.accreditation_type = changes.accreditationType;
      }

      if (changes.displayName !== undefined) {
        columnValues.display_name = changes.displayName;
      }

      if (changes.guildId !== undefined) {
        columnValues.guild_id = changes.guildId;
      }

      if (changes.internalComment !== undefined) {
        columnValues.internal_comment = changes.internalComment;
      }

      if (changes.isCollective !== undefined) {
        columnValues.is_collective = changes.isCollective ? 1 : 0;
      }

      if (changes.organizerId !== undefined) {
        columnValues.organizer_id = changes.organizerId;
      }

      if (changes.userId !== undefined) {
        columnValues.user_id = changes.userId;
      }

      const target = sql`f.id = ${input.id} AND f.event_id = ${input.eventId} AND f.deleted_at IS NULL`;

      if (Object.keys(columnValues).length > 0) {
        const rows = yield* sql`
        UPDATE facilitator SET ${sql.update(columnValues)}
        WHERE id = ${input.id} AND event_id = ${input.eventId} AND deleted_at IS NULL RETURNING id
      `.pipe(decodeRows("FacilitatorStore.update", IdRow));

        yield* requireRow({ entity: "Facilitator", key: String(input.id) })(
          rows
        );
      }

      return yield* readWhere(
        "FacilitatorStore.update",
        String(input.id),
        target
      );
    });

    const setAccreditation = Effect.fn("FacilitatorStore.setAccreditation")(
      function* setAccreditation(options: typeof AccreditationInput.Type) {
        const input = yield* decodeInput(
          "FacilitatorStore.setAccreditation",
          AccreditationInput
        )(options);

        if (input.ids.length === 0) {
          return 0;
        }

        const rows = yield* sql`
      UPDATE facilitator SET accreditation_type = ${input.accreditationType}
      WHERE event_id = ${input.eventId} AND deleted_at IS NULL AND ${sql.in("id", input.ids)} RETURNING id
    `.pipe(decodeRows("FacilitatorStore.setAccreditation", IdRow));

        return rows.length;
      }
    );

    const claim = Effect.fn("FacilitatorStore.claim")(function* claim(
      options: typeof ClaimInput.Type
    ) {
      const input = yield* decodeInput(
        "FacilitatorStore.claim",
        ClaimInput
      )(options);

      const rows = yield* sql`
      UPDATE facilitator SET organizer_id = ${input.organizerId}
      WHERE id = ${input.id} AND event_id = ${input.eventId} AND deleted_at IS NULL AND organizer_id IS NULL
      RETURNING id
    `.pipe(decodeRows("FacilitatorStore.claim", IdRow));

      return rows.length > 0;
    });

    const release = Effect.fn("FacilitatorStore.release")(function* release(
      options: typeof ReleaseInput.Type
    ) {
      const input = yield* decodeInput(
        "FacilitatorStore.release",
        ReleaseInput
      )(options);

      const holder =
        input.organizerId === null
          ? sql`1 = 1`
          : sql`organizer_id = ${input.organizerId}`;

      const rows = yield* sql`
      UPDATE facilitator SET organizer_id = NULL
      WHERE id = ${input.id} AND event_id = ${input.eventId} AND deleted_at IS NULL
        AND organizer_id IS NOT NULL AND ${holder}
      RETURNING id
    `.pipe(decodeRows("FacilitatorStore.release", IdRow));

      return rows.length > 0;
    });

    const countSessions = Effect.fn("FacilitatorStore.countSessions")(
      function* countSessions(scope: typeof ScopeInput.Type) {
        const input = yield* decodeInput(
          "FacilitatorStore.countSessions",
          ScopeInput
        )(scope);

        const row = yield* sql`
      SELECT
        COUNT(DISTINCT CASE WHEN s.deleted_at IS NULL THEN s.id END) AS live,
        COUNT(DISTINCT CASE WHEN s.deleted_at IS NOT NULL THEN s.id END) AS deleted
      FROM facilitator f
      LEFT JOIN session_facilitators sf ON sf.facilitator_id = f.id
      LEFT JOIN session s ON s.id = sf.session_id
      WHERE f.id = ${input.id} AND f.event_id = ${input.eventId}
    `.pipe(
          decodeFirst(
            "FacilitatorStore.countSessions",
            FacilitatorSessionCounts
          )
        );

        return Option.getOrElse(row, () => ({ deleted: 0, live: 0 }));
      }
    );

    const softDelete = Effect.fn("FacilitatorStore.softDelete")(
      function* softDelete(scope: typeof ScopeInput.Type) {
        const input = yield* decodeInput(
          "FacilitatorStore.softDelete",
          ScopeInput
        )(scope);

        const now = toSqlDateTime(yield* DateTime.now);

        const rows = yield* sql`
      UPDATE facilitator SET deleted_at = ${now}
      WHERE id = ${input.id} AND event_id = ${input.eventId} AND deleted_at IS NULL RETURNING id
    `.pipe(decodeRows("FacilitatorStore.softDelete", IdRow));

        yield* requireRow({ entity: "Facilitator", key: String(input.id) })(
          rows
        );
      }
    );

    const restore = Effect.fn("FacilitatorStore.restore")(function* restore(
      scope: typeof ScopeInput.Type
    ) {
      const input = yield* decodeInput(
        "FacilitatorStore.restore",
        ScopeInput
      )(scope);

      const rows = yield* sql`
      UPDATE facilitator SET deleted_at = NULL
      WHERE id = ${input.id} AND event_id = ${input.eventId} AND deleted_at IS NOT NULL RETURNING id
    `.pipe(decodeRows("FacilitatorStore.restore", IdRow));

      yield* requireRow({ entity: "Facilitator", key: String(input.id) })(rows);
    });

    return FacilitatorStore.of({
      claim,
      countSessions,
      create,
      findByDisplayName,
      findByUser,
      listByEvent,
      listDeletedByEvent,
      readBySlug,
      readBySlugIncludingDeleted,
      readInEvent,
      release,
      restore,
      setAccreditation,
      slugExists,
      softDelete,
      update,
    });
  }
);

export const FacilitatorStoreLive = Layer.effect(
  FacilitatorStore,
  makeFacilitatorStore
);
