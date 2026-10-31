import {
  AgendaItemId,
  EventId,
  FacilitatorId,
  NewSession,
  NotFound,
  NO_LOCATION,
  SessionChanges,
  SessionFieldValueWrite,
  SessionId,
  SessionListFilters,
  SessionListItem,
  SessionStore,
  StoreError,
  SpaceId,
  SpaceOption,
  TimeSlotId,
  TrackId,
  TrackSessionCounts,
  UserId,
} from "@zagrajmy/core";
import type {
  Facilitator,
  Location,
  SessionCard,
  SessionFieldAnswer,
  SessionSeat,
  TimeSlot,
  UserSummary,
} from "@zagrajmy/core";
import { DateTime, Effect, Layer, Option, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";
import type { Fragment } from "effect/sql/Statement";

import {
  decodeInput,
  decodeOne,
  decodeRows,
  IdRow,
  likeContains,
  pythonJson,
  requireRow,
  SqlBool,
  SqlDateTime,
  storeFailure,
  toSqlDateTime,
} from "./rows.js";
import { seatsQuery } from "./seats.js";
import {
  FACILITATOR_COLUMNS,
  FIELD_ANSWER_COLUMNS,
  FacilitatorRow,
  FieldAnswerRow,
  LocationRow,
  SeatsRow,
  SESSION_COLUMNS,
  SessionRow,
  TimeSlotRow,
  USER_SUMMARY_COLUMNS,
  UserSummaryRow,
} from "./shared-rows.js";
import { locationsQuery } from "./space-store.js";
import { PUBLIC_SCHEDULED_SESSION, ROW_BUDGET } from "./sql-fragments.js";

const CardRow = Schema.Struct({
  ...SessionRow.fields,
  agendaEndTime: Schema.NullOr(SqlDateTime),
  agendaId: Schema.NullOr(AgendaItemId),
  agendaSpaceId: Schema.NullOr(SpaceId),
  agendaStartTime: Schema.NullOr(SqlDateTime),
  categoryName: Schema.NullOr(Schema.String),
});

type CardRow = typeof CardRow.Type;

const SeatRow = Schema.Struct({
  ...UserSummaryRow.fields,
  seatCreationTime: SqlDateTime,
  seatStatus: Schema.Literals(["confirmed", "waiting", "offered"]),
  sessionId: SessionId,
});

const SessionIdRow = Schema.Struct({ id: SessionId });

const TrackNameRow = Schema.Struct({
  name: Schema.String,
  sessionId: SessionId,
});

const SlotRow = Schema.Struct({ ...TimeSlotRow.fields, sessionId: SessionId });

const FacilitatorBySessionRow = Schema.Struct({
  ...FacilitatorRow.fields,
  sessionId: SessionId,
});

const ListItemRow = Schema.Struct({
  ...SessionListItem.fields,
  creationTime: SqlDateTime,
  isDeleted: SqlBool,
  isScheduled: SqlBool,
});

const CountsRow = Schema.Struct({
  ...TrackSessionCounts.fields,
});

const ScheduledInput = Schema.Struct({
  eventId: EventId,
  now: Schema.DateTimeUtc,
  rosterUpTo: Schema.Int,
});

const OneScheduledInput = Schema.Struct({
  eventId: EventId,
  now: Schema.DateTimeUtc,
  sessionId: SessionId,
});

const ProposalsInput = Schema.Struct({
  eventId: EventId,
  now: Schema.DateTimeUtc,
  presenterId: Schema.NullOr(UserId),
});

const ScopeInput = Schema.Struct({ eventId: EventId, id: SessionId });

const ListInput = Schema.Struct({
  eventId: EventId,
  filters: SessionListFilters,
});

const ByFacilitatorInput = Schema.Struct({
  eventId: EventId,
  facilitatorId: FacilitatorId,
});

const SlugInput = Schema.Struct({ eventId: EventId, slug: Schema.String });

const UpdateInput = Schema.Struct({
  changes: SessionChanges,
  eventId: EventId,
  id: SessionId,
});

const TracksInput = Schema.Struct({
  eventId: EventId,
  sessionId: SessionId,
  trackIds: Schema.Array(TrackId),
});

const SlotsInput = Schema.Struct({
  eventId: EventId,
  sessionId: SessionId,
  timeSlotIds: Schema.Array(TimeSlotId),
});

const FacilitatorsInput = Schema.Struct({
  eventId: EventId,
  facilitatorIds: Schema.Array(FacilitatorId),
  sessionId: SessionId,
});

const FieldValuesInput = Schema.Struct({
  sessionId: SessionId,
  values: Schema.Array(SessionFieldValueWrite),
});

const SORT_COLUMNS = {
  category: "c.name",
  created: "s.creation_time",
  host: "s.facilitator_name",
  status: "s.status",
  title: "s.title",
} as const;

const groupBy = <A, K>(rows: readonly A[], key: (row: A) => K) => {
  const groups = new Map<K, A[]>();

  for (const row of rows) {
    const group = groups.get(key(row));

    if (group === undefined) {
      groups.set(key(row), [row]);
    } else {
      group.push(row);
    }
  }

  return groups;
};

const answerOf = (row: typeof FieldAnswerRow.Type): SessionFieldAnswer => ({
  allowCustom: row.allowCustom,
  fieldIcon: row.fieldIcon,
  fieldId: row.fieldId,
  fieldName: row.fieldName,
  fieldOrder: row.fieldOrder,
  fieldQuestion: row.fieldQuestion,
  fieldSlug: row.fieldSlug,
  fieldType: row.fieldType,
  isPublic: row.isPublic,
  showOnCards: row.showOnCards,
  value: row.value,
});

const summaryOf = (row: typeof UserSummaryRow.Type): UserSummary => ({
  avatarUrl: row.avatarUrl,
  email: row.email,
  id: row.id,
  managerId: row.managerId,
  name: row.name,
  slug: row.slug,
  useGravatar: row.useGravatar,
  userType: row.userType,
  username: row.username,
});

const sessionOf = (row: CardRow) => ({
  categoryId: row.categoryId,
  contactEmail: row.contactEmail,
  coverImage: row.coverImage,
  coverImageOriginalName: row.coverImageOriginalName,
  creationTime: row.creationTime,
  deletedAt: row.deletedAt,
  description: row.description,
  duration: row.duration,
  eventId: row.eventId,
  facilitatorName: row.facilitatorName,
  id: row.id,
  ident: row.ident,
  minAge: row.minAge,
  modificationTime: row.modificationTime,
  participantsLimit: row.participantsLimit,
  presenterId: row.presenterId,
  scheduleConfirmed: row.scheduleConfirmed,
  slug: row.slug,
  status: row.status,
  title: row.title,
});

const agendaOf = (row: CardRow) =>
  row.agendaId === null ||
  row.agendaSpaceId === null ||
  row.agendaStartTime === null ||
  row.agendaEndTime === null
    ? null
    : {
        endTime: row.agendaEndTime,
        id: row.agendaId,
        scheduleConfirmed: row.scheduleConfirmed,
        sessionId: row.id,
        spaceId: row.agendaSpaceId,
        startTime: row.agendaStartTime,
      };

export const makeSessionStore = Effect.gen(function* makeSessionStore() {
  const sql = yield* SqlClient;
  const sessionColumns = sql.literal(SESSION_COLUMNS);
  const publicScheduled = sql.literal(PUBLIC_SCHEDULED_SESSION);

  const cardsFor = Effect.fn("SessionStore.cardsFor")(
    function* cardsFor(options: {
      readonly operation: string;
      readonly eventId: EventId;
      readonly scope: Fragment;
      readonly order: Fragment;
      readonly now: DateTime.Utc;
      readonly withRosterBelow: number;
      readonly withLocations: boolean;
      readonly withPreferredSlots: boolean;
      readonly limit: number;
    }) {
      const { operation, eventId, scope, order, limit } = options;
      const now = toSqlDateTime(options.now);

      const rows = yield* sql`
      SELECT ${sessionColumns}, c.name AS categoryName,
        a.id AS agendaId, a.space_id AS agendaSpaceId,
        a.start_time AS agendaStartTime, a.end_time AS agendaEndTime
      FROM session s
      LEFT JOIN agenda_item a ON a.session_id = s.id
      LEFT JOIN proposal_category c ON c.id = s.category_id
      WHERE ${scope}
      ORDER BY ${order}
      LIMIT ${limit}
    `.pipe(decodeRows(operation, CardRow));

      if (rows.length === 0) {
        return [];
      }

      const sessionIds = sql`SELECT s.id FROM session s WHERE ${scope}`;

      const presenterIds = [
        ...new Set(
          rows.flatMap((row) =>
            row.presenterId === null ? [] : [row.presenterId]
          )
        ),
      ];

      const [
        presenters,
        answers,
        trackNames,
        seatRows,
        stats,
        locations,
        slots,
      ] = yield* Effect.all(
        [
          presenterIds.length === 0
            ? Effect.succeed([])
            : sql`SELECT ${sql.literal(USER_SUMMARY_COLUMNS("u"))} FROM user u WHERE ${sql.in("u.id", presenterIds)}`.pipe(
                decodeRows(operation, UserSummaryRow)
              ),
          sql`
          SELECT ${sql.literal(FIELD_ANSWER_COLUMNS)}
          FROM session_field_value v JOIN session_field f ON f.id = v.field_id
          WHERE v.session_id IN (${sessionIds}) AND f.is_public = 1
          ORDER BY f."order", f.name, v.id
        `.pipe(decodeRows(operation, FieldAnswerRow)),
          sql`
          SELECT st.session_id AS sessionId, t.name AS name
          FROM session_tracks st JOIN track t ON t.id = st.track_id
          WHERE st.session_id IN (${sessionIds})
          ORDER BY t.name, t.id
        `.pipe(decodeRows(operation, TrackNameRow)),
          rows.length < options.withRosterBelow
            ? sql`
              SELECT p.session_id AS sessionId, p.status AS seatStatus,
                p.creation_time AS seatCreationTime, ${sql.literal(USER_SUMMARY_COLUMNS("u"))}
              FROM session_participant p JOIN user u ON u.id = p.user_id
              WHERE p.session_id IN (${sessionIds})
              ORDER BY p.id
              LIMIT ${ROW_BUDGET.participationsPerSession * rows.length}
            `.pipe(decodeRows(operation, SeatRow))
            : Effect.succeed([]),
          seatsQuery({ limit, now, sql, where: scope }).pipe(
            decodeRows(operation, SeatsRow)
          ),
          options.withLocations
            ? locationsQuery(sql, eventId).pipe(
                decodeRows(operation, LocationRow)
              )
            : Effect.succeed([]),
          options.withPreferredSlots
            ? sql`
              SELECT sts.session_id AS sessionId, ts.id AS id, ts.event_id AS eventId,
                ts.start_time AS startTime, ts.end_time AS endTime
              FROM session_time_slots sts JOIN time_slot ts ON ts.id = sts.timeslot_id
              WHERE sts.session_id IN (${sessionIds})
              ORDER BY ts.start_time, ts.id
            `.pipe(decodeRows(operation, SlotRow))
            : Effect.succeed([]),
        ],
        { concurrency: 1 }
      );

      const presenterById = new Map(
        presenters.map((row) => [row.id, summaryOf(row)])
      );

      const answersBySession = groupBy(answers, (row) => row.sessionId);
      const tracksBySession = groupBy(trackNames, (row) => row.sessionId);
      const seatsBySession = groupBy(seatRows, (row) => row.sessionId);
      const statsBySession = new Map(stats.map((row) => [row.sessionId, row]));

      const locationBySpace = new Map<number, Location>(
        locations.map((row) => [row.spaceId, row])
      );

      const slotsBySession = groupBy(slots, (row) => row.sessionId);

      const cards: SessionCard[] = [];

      for (const row of rows) {
        const seatStats = statsBySession.get(row.id);

        if (seatStats === undefined) {
          continue;
        }

        const seats: SessionSeat[] = (seatsBySession.get(row.id) ?? []).map(
          (seat) => ({
            creationTime: seat.seatCreationTime,
            status: seat.seatStatus,
            user: summaryOf(seat),
          })
        );

        const preferredTimeSlots: TimeSlot[] = (
          slotsBySession.get(row.id) ?? []
        ).map((slot) => ({
          endTime: slot.endTime,
          eventId: slot.eventId,
          id: slot.id,
          startTime: slot.startTime,
        }));

        cards.push({
          agendaItem: agendaOf(row),
          categoryName: row.categoryName ?? "",
          fieldValues: (answersBySession.get(row.id) ?? []).map(answerOf),
          location:
            row.agendaSpaceId === null
              ? NO_LOCATION
              : (locationBySpace.get(row.agendaSpaceId) ?? NO_LOCATION),
          participations: seats,
          preferredTimeSlots,
          presenter:
            row.presenterId === null
              ? null
              : (presenterById.get(row.presenterId) ?? null),
          seats: seatStats,
          session: sessionOf(row),
          trackNames: (tracksBySession.get(row.id) ?? []).map(
            (track) => track.name
          ),
        });
      }

      return cards;
    }
  );

  const listScheduledCards = Effect.fn("SessionStore.listScheduledCards")(
    function* listScheduledCards(options: typeof ScheduledInput.Type) {
      const input = yield* decodeInput(
        "SessionStore.listScheduledCards",
        ScheduledInput
      )(options);

      return yield* cardsFor({
        eventId: input.eventId,
        limit: ROW_BUDGET.scheduledSessions,
        now: input.now,
        operation: "SessionStore.listScheduledCards",
        order: sql`a.start_time, s.id`,
        scope: sql`s.event_id = ${input.eventId} AND ${publicScheduled}`,
        withLocations: true,
        withPreferredSlots: false,
        withRosterBelow: input.rosterUpTo,
      });
    }
  );

  const readScheduledCard = Effect.fn("SessionStore.readScheduledCard")(
    function* readScheduledCard(options: typeof OneScheduledInput.Type) {
      const input = yield* decodeInput(
        "SessionStore.readScheduledCard",
        OneScheduledInput
      )(options);

      const cards = yield* cardsFor({
        eventId: input.eventId,
        limit: 1,
        now: input.now,
        operation: "SessionStore.readScheduledCard",
        order: sql`s.id`,
        scope: sql`s.event_id = ${input.eventId} AND s.id = ${input.sessionId} AND ${publicScheduled}`,
        withLocations: true,
        withPreferredSlots: false,
        withRosterBelow: 2,
      });

      return Option.fromNullishOr(cards[0]);
    }
  );

  const listProposalCards = Effect.fn("SessionStore.listProposalCards")(
    function* listProposalCards(options: typeof ProposalsInput.Type) {
      const input = yield* decodeInput(
        "SessionStore.listProposalCards",
        ProposalsInput
      )(options);

      const presenter =
        input.presenterId === null
          ? sql`1 = 1`
          : sql`s.presenter_id = ${input.presenterId}`;

      return yield* cardsFor({
        eventId: input.eventId,
        limit: ROW_BUDGET.proposalCards,
        now: input.now,
        operation: "SessionStore.listProposalCards",
        order: sql`s.creation_time DESC, s.id DESC`,
        scope: sql`s.event_id = ${input.eventId} AND s.deleted_at IS NULL AND s.status = 'pending'
        AND NOT EXISTS (SELECT 1 FROM agenda_item na WHERE na.session_id = s.id) AND ${presenter}`,
        withLocations: false,
        withPreferredSlots: true,
        withRosterBelow: Number.MAX_SAFE_INTEGER,
      });
    }
  );

  const read = Effect.fn("SessionStore.read")(function* read(id: SessionId) {
    const valid = yield* decodeInput("SessionStore.read", SessionId)(id);

    return yield* sql`SELECT ${sessionColumns} FROM session s WHERE s.id = ${valid} AND s.deleted_at IS NULL`.pipe(
      decodeOne({
        entity: "Session",
        key: String(valid),
        operation: "SessionStore.read",
        row: SessionRow,
      })
    );
  });

  const readInEvent = Effect.fn("SessionStore.readInEvent")(
    function* readInEvent(scope: typeof ScopeInput.Type) {
      const input = yield* decodeInput(
        "SessionStore.readInEvent",
        ScopeInput
      )(scope);

      return yield* sql`
      SELECT ${sessionColumns} FROM session s JOIN proposal_category c ON c.id = s.category_id
      WHERE s.id = ${input.id} AND c.event_id = ${input.eventId} AND s.deleted_at IS NULL
    `.pipe(
        decodeOne({
          entity: "Session",
          key: String(input.id),
          operation: "SessionStore.readInEvent",
          row: SessionRow,
        })
      );
    }
  );

  const listItems = (options: {
    readonly operation: string;
    readonly where: Fragment;
    readonly order: Fragment;
    readonly limit: number;
  }) =>
    sql`
      SELECT s.id AS id, s.title AS title, s.facilitator_name AS facilitatorName,
        COALESCE(c.name, '') AS categoryName, s.status AS status,
        s.creation_time AS creationTime,
        EXISTS (SELECT 1 FROM agenda_item ia WHERE ia.session_id = s.id) AS isScheduled,
        (s.deleted_at IS NOT NULL) AS isDeleted
      FROM session s LEFT JOIN proposal_category c ON c.id = s.category_id
      WHERE ${options.where}
      ORDER BY ${options.order}
      LIMIT ${options.limit}
    `.pipe(decodeRows(options.operation, ListItemRow));

  const listByEvent = Effect.fn("SessionStore.listByEvent")(
    function* listByEvent(options: typeof ListInput.Type) {
      const input = yield* decodeInput(
        "SessionStore.listByEvent",
        ListInput
      )(options);

      const { filters } = input;

      const clauses: Fragment[] = [
        sql`s.deleted_at IS NULL`,
        sql`s.category_id IN (SELECT id FROM proposal_category WHERE event_id = ${input.eventId})`,
      ];

      if (filters.categoryId !== undefined) {
        clauses.push(sql`s.category_id = ${filters.categoryId}`);
      }

      if (filters.status !== undefined) {
        clauses.push(sql`s.status = ${filters.status}`);
      }

      if (filters.scheduled !== undefined) {
        clauses.push(
          filters.scheduled
            ? sql`EXISTS (SELECT 1 FROM agenda_item fa WHERE fa.session_id = s.id)`
            : sql`NOT EXISTS (SELECT 1 FROM agenda_item fa WHERE fa.session_id = s.id)`
        );
      }

      for (const filter of filters.fieldFilters ?? []) {
        clauses.push(sql`EXISTS (
        SELECT 1 FROM session_field_value fv
        WHERE fv.session_id = s.id AND fv.field_id = ${filter.fieldId} AND fv.value = ${pythonJson(filter.value)})`);
      }

      if (filters.search !== undefined && filters.search !== "") {
        const raw = likeContains(filters.search);
        const encoded = likeContains(pythonJson(filters.search).slice(1, -1));
        clauses.push(sql`(
        s.title LIKE ${raw} ESCAPE '\\'
        OR s.facilitator_name LIKE ${raw} ESCAPE '\\'
        OR EXISTS (SELECT 1 FROM user pu WHERE pu.id = s.presenter_id AND pu.name LIKE ${raw} ESCAPE '\\')
        OR EXISTS (SELECT 1 FROM session_field_value sv WHERE sv.session_id = s.id
          AND (sv.value LIKE ${raw} ESCAPE '\\' OR sv.value LIKE ${encoded} ESCAPE '\\')))`);
      }

      if (filters.trackId !== undefined) {
        clauses.push(
          sql`EXISTS (SELECT 1 FROM session_tracks ft WHERE ft.session_id = s.id AND ft.track_id = ${filters.trackId})`
        );
      }

      if (filters.multiTracks === true) {
        clauses.push(
          sql`(SELECT COUNT(DISTINCT mt.track_id) FROM session_tracks mt WHERE mt.session_id = s.id) > 1`
        );
      }

      const { sort } = filters;

      const direction = sql.literal(sort?.descending === true ? "DESC" : "ASC");
      let order = sql`s.creation_time DESC`;

      if (sort !== undefined && "fieldId" in sort) {
        order = sql`(SELECT sfv.value FROM session_field_value sfv WHERE sfv.session_id = s.id AND sfv.field_id = ${sort.fieldId} LIMIT 1) ${direction}, s.id DESC`;
      } else if (sort !== undefined) {
        order = sql`${sql.literal(SORT_COLUMNS[sort.key])} ${direction}, s.id DESC`;
      }

      return yield* listItems({
        limit: ROW_BUDGET.panelSessions,
        operation: "SessionStore.listByEvent",
        order,
        where: sql.and(clauses),
      });
    }
  );

  const listDeletedByEvent = Effect.fn("SessionStore.listDeletedByEvent")(
    function* listDeletedByEvent(eventId: EventId) {
      const valid = yield* decodeInput(
        "SessionStore.listDeletedByEvent",
        EventId
      )(eventId);

      return yield* listItems({
        limit: ROW_BUDGET.panelSessions,
        operation: "SessionStore.listDeletedByEvent",
        order: sql`s.creation_time DESC, s.id DESC`,
        where: sql`s.deleted_at IS NOT NULL AND c.event_id = ${valid}`,
      });
    }
  );

  const listByFacilitator = Effect.fn("SessionStore.listByFacilitator")(
    function* listByFacilitator(options: typeof ByFacilitatorInput.Type) {
      const input = yield* decodeInput(
        "SessionStore.listByFacilitator",
        ByFacilitatorInput
      )(options);

      return yield* listItems({
        limit: ROW_BUDGET.panelSessions,
        operation: "SessionStore.listByFacilitator",
        order: sql`s.creation_time DESC, s.id DESC`,
        where: sql`s.id IN (
        SELECT sf.session_id FROM session_facilitators sf JOIN facilitator f ON f.id = sf.facilitator_id
        WHERE sf.facilitator_id = ${input.facilitatorId} AND f.event_id = ${input.eventId})`,
      });
    }
  );

  const slugExists = Effect.fn("SessionStore.slugExists")(function* slugExists(
    options: typeof SlugInput.Type
  ) {
    const input = yield* decodeInput(
      "SessionStore.slugExists",
      SlugInput
    )(options);

    const rows = yield* sql`
      SELECT id FROM session WHERE event_id = ${input.eventId} AND slug = ${input.slug} AND deleted_at IS NULL LIMIT 1
    `.pipe(decodeRows("SessionStore.slugExists", IdRow));

    return rows.length > 0;
  });

  const requireAllInEvent = Effect.fn("SessionStore.requireAllInEvent")(
    function* requireAllInEvent(options: {
      readonly operation: string;
      readonly entity: string;
      readonly table: "facilitator" | "time_slot" | "track";
      readonly eventId: EventId;
      readonly ids: readonly number[];
    }) {
      const wanted = [...new Set(options.ids)];

      if (wanted.length === 0) {
        return yield* Effect.void;
      }

      const alive =
        options.table === "facilitator" ? sql`AND deleted_at IS NULL` : sql``;

      const found = yield* sql`
      SELECT id FROM ${sql(options.table)}
      WHERE event_id = ${options.eventId} AND ${sql.in("id", wanted)} ${alive}
    `.pipe(decodeRows(options.operation, IdRow));

      const foundIds = new Set(found.map((row) => row.id));
      const missing = wanted.filter((id) => !foundIds.has(id));

      if (missing.length > 0) {
        return yield* new NotFound({
          entity: options.entity,
          key: missing.join(","),
        });
      }

      return yield* Effect.void;
    }
  );

  const linkMany = (options: {
    readonly table:
      | "session_facilitators"
      | "session_time_slots"
      | "session_tracks";
    readonly column: "facilitator_id" | "timeslot_id" | "track_id";
    readonly sessionId: SessionId;
    readonly ids: readonly number[];
  }) => {
    const ids = [...new Set(options.ids)];

    return ids.length === 0
      ? Effect.void
      : sql`INSERT INTO ${sql(options.table)} ${sql.insert(
          ids.map((id) => ({
            [options.column]: id,
            session_id: options.sessionId,
          }))
        )}`.pipe(Effect.asVoid);
  };

  const create = Effect.fn("SessionStore.create")(function* create(
    session: typeof NewSession.Type
  ) {
    const input = yield* decodeInput(
      "SessionStore.create",
      NewSession
    )(session);

    const now = toSqlDateTime(yield* DateTime.now);
    const operation = "SessionStore.create";

    return yield* Effect.gen(function* insertSession() {
      yield* requireAllInEvent({
        entity: "Facilitator",
        eventId: input.eventId,
        ids: input.facilitatorIds,
        operation,
        table: "facilitator",
      });
      yield* requireAllInEvent({
        entity: "TimeSlot",
        eventId: input.eventId,
        ids: input.timeSlotIds,
        operation,
        table: "time_slot",
      });
      yield* requireAllInEvent({
        entity: "Track",
        eventId: input.eventId,
        ids: input.trackIds,
        operation,
        table: "track",
      });

      const [inserted] = yield* sql`
        INSERT INTO session ${sql.insert({
          category_id: input.categoryId,
          contact_email: input.contactEmail,
          cover_image: "",
          cover_image_original_name: "",
          creation_time: now,
          deleted_at: null,
          description: input.description,
          duration: input.duration,
          event_id: input.eventId,
          facilitator_name: input.facilitatorName,
          ident: input.ident,
          min_age: input.minAge,
          modification_time: now,
          participants_limit: input.participantsLimit,
          presenter_id: input.presenterId,
          schedule_confirmed: input.scheduleConfirmed ? 1 : 0,
          slug: input.slug,
          status: input.status,
          title: input.title,
        })} RETURNING id
      `.pipe(decodeRows(operation, SessionIdRow));

      if (inserted === undefined) {
        return yield* new StoreError({
          operation,
          reason: "insert returned no id",
        });
      }

      const sessionId = inserted.id;
      yield* linkMany({
        column: "timeslot_id",
        ids: input.timeSlotIds,
        sessionId,
        table: "session_time_slots",
      });
      yield* linkMany({
        column: "facilitator_id",
        ids: input.facilitatorIds,
        sessionId,
        table: "session_facilitators",
      });
      yield* linkMany({
        column: "track_id",
        ids: input.trackIds,
        sessionId,
        table: "session_tracks",
      });

      return sessionId;
    }).pipe(
      sql.withTransaction,
      Effect.catchTag("SqlError", (cause) =>
        storeFailure(operation)(Effect.fail(cause))
      )
    );
  });

  const update = Effect.fn("SessionStore.update")(function* update(
    options: typeof UpdateInput.Type
  ) {
    const input = yield* decodeInput(
      "SessionStore.update",
      UpdateInput
    )(options);

    const { changes } = input;
    const columns: Record<string, string | number | null> = {};

    if (changes.categoryId !== undefined) {
      columns.category_id = changes.categoryId;
    }

    if (changes.contactEmail !== undefined) {
      columns.contact_email = changes.contactEmail;
    }

    if (changes.description !== undefined) {
      columns.description = changes.description;
    }

    if (changes.duration !== undefined) {
      columns.duration = changes.duration;
    }

    if (changes.facilitatorName !== undefined) {
      columns.facilitator_name = changes.facilitatorName;
    }

    if (changes.minAge !== undefined) {
      columns.min_age = changes.minAge;
    }

    if (changes.participantsLimit !== undefined) {
      columns.participants_limit = changes.participantsLimit;
    }

    if (changes.scheduleConfirmed !== undefined) {
      columns.schedule_confirmed = changes.scheduleConfirmed ? 1 : 0;
    }

    if (changes.slug !== undefined) {
      columns.slug = changes.slug;
    }

    if (changes.status !== undefined) {
      columns.status = changes.status;
    }

    if (changes.title !== undefined) {
      columns.title = changes.title;
    }

    const target = sql`id = ${input.id} AND event_id = ${input.eventId} AND deleted_at IS NULL`;

    const rows =
      Object.keys(columns).length === 0
        ? yield* sql`SELECT id FROM session WHERE ${target}`.pipe(
            decodeRows("SessionStore.update", IdRow)
          )
        : yield* sql`UPDATE session SET ${sql.update(columns)} WHERE ${target} RETURNING id`.pipe(
            decodeRows("SessionStore.update", IdRow)
          );

    yield* requireRow({ entity: "Session", key: String(input.id) })(rows);
  });

  const softDelete = Effect.fn("SessionStore.softDelete")(function* softDelete(
    scope: typeof ScopeInput.Type
  ) {
    const input = yield* decodeInput(
      "SessionStore.softDelete",
      ScopeInput
    )(scope);

    const now = toSqlDateTime(yield* DateTime.now);

    const rows = yield* sql`
      UPDATE session SET deleted_at = ${now}
      WHERE id = ${input.id} AND event_id = ${input.eventId} AND deleted_at IS NULL RETURNING id
    `.pipe(decodeRows("SessionStore.softDelete", IdRow));

    yield* requireRow({ entity: "Session", key: String(input.id) })(rows);
  });

  const restore = Effect.fn("SessionStore.restore")(function* restore(
    scope: typeof ScopeInput.Type
  ) {
    const input = yield* decodeInput("SessionStore.restore", ScopeInput)(scope);

    const rows = yield* sql`
      UPDATE session SET deleted_at = NULL
      WHERE id = ${input.id} AND deleted_at IS NOT NULL
        AND category_id IN (SELECT id FROM proposal_category WHERE event_id = ${input.eventId})
      RETURNING id
    `.pipe(decodeRows("SessionStore.restore", IdRow));

    yield* requireRow({ entity: "Session", key: String(input.id) })(rows);
  });

  const requireAliveInEvent = (
    operation: string,
    eventId: EventId,
    sessionId: SessionId
  ) =>
    sql`SELECT id FROM session WHERE id = ${sessionId} AND event_id = ${eventId} AND deleted_at IS NULL`.pipe(
      decodeRows(operation, IdRow),
      Effect.flatMap(requireRow({ entity: "Session", key: String(sessionId) }))
    );

  const replaceLinks = (options: {
    readonly operation: string;
    readonly eventId: EventId;
    readonly sessionId: SessionId;
    readonly table:
      | "session_facilitators"
      | "session_time_slots"
      | "session_tracks";
    readonly column: "facilitator_id" | "timeslot_id" | "track_id";
    readonly owner: "facilitator" | "time_slot" | "track";
    readonly entity: string;
    readonly ids: readonly number[];
  }) =>
    Effect.gen(function* replace() {
      yield* requireAliveInEvent(
        options.operation,
        options.eventId,
        options.sessionId
      );
      yield* requireAllInEvent({
        entity: options.entity,
        eventId: options.eventId,
        ids: options.ids,
        operation: options.operation,
        table: options.owner,
      });
      yield* sql`DELETE FROM ${sql(options.table)} WHERE session_id = ${options.sessionId}`;
      yield* linkMany(options);
    }).pipe(
      sql.withTransaction,
      Effect.catchTag("SqlError", (cause) =>
        storeFailure(options.operation)(Effect.fail(cause))
      )
    );

  const setTracks = Effect.fn("SessionStore.setTracks")(function* setTracks(
    options: typeof TracksInput.Type
  ) {
    const input = yield* decodeInput(
      "SessionStore.setTracks",
      TracksInput
    )(options);

    yield* replaceLinks({
      column: "track_id",
      entity: "Track",
      eventId: input.eventId,
      ids: input.trackIds,
      operation: "SessionStore.setTracks",
      owner: "track",
      sessionId: input.sessionId,
      table: "session_tracks",
    });
  });

  const setTimeSlots = Effect.fn("SessionStore.setTimeSlots")(
    function* setTimeSlots(options: typeof SlotsInput.Type) {
      const input = yield* decodeInput(
        "SessionStore.setTimeSlots",
        SlotsInput
      )(options);

      yield* replaceLinks({
        column: "timeslot_id",
        entity: "TimeSlot",
        eventId: input.eventId,
        ids: input.timeSlotIds,
        operation: "SessionStore.setTimeSlots",
        owner: "time_slot",
        sessionId: input.sessionId,
        table: "session_time_slots",
      });
    }
  );

  const setFacilitators = Effect.fn("SessionStore.setFacilitators")(
    function* setFacilitators(options: typeof FacilitatorsInput.Type) {
      const input = yield* decodeInput(
        "SessionStore.setFacilitators",
        FacilitatorsInput
      )(options);

      yield* replaceLinks({
        column: "facilitator_id",
        entity: "Facilitator",
        eventId: input.eventId,
        ids: input.facilitatorIds,
        operation: "SessionStore.setFacilitators",
        owner: "facilitator",
        sessionId: input.sessionId,
        table: "session_facilitators",
      });
    }
  );

  const readTrackIds = Effect.fn("SessionStore.readTrackIds")(
    function* readTrackIds(sessionId: SessionId) {
      const valid = yield* decodeInput(
        "SessionStore.readTrackIds",
        SessionId
      )(sessionId);

      const rows = yield* sql`
      SELECT st.track_id AS id FROM session_tracks st JOIN track t ON t.id = st.track_id
      WHERE st.session_id = ${valid} ORDER BY t.name LIMIT ${ROW_BUDGET.eventTracks}
    `.pipe(
        decodeRows("SessionStore.readTrackIds", Schema.Struct({ id: TrackId }))
      );

      return rows.map((row) => row.id);
    }
  );

  const readPreferredTimeSlots = Effect.fn(
    "SessionStore.readPreferredTimeSlots"
  )(function* readPreferredTimeSlots(sessionId: SessionId) {
    const valid = yield* decodeInput(
      "SessionStore.readPreferredTimeSlots",
      SessionId
    )(sessionId);

    return yield* sql`
      SELECT ts.id AS id, ts.event_id AS eventId, ts.start_time AS startTime, ts.end_time AS endTime
      FROM session_time_slots sts JOIN time_slot ts ON ts.id = sts.timeslot_id
      WHERE sts.session_id = ${valid} ORDER BY ts.start_time, ts.id LIMIT ${ROW_BUDGET.eventTimeSlots}
    `.pipe(decodeRows("SessionStore.readPreferredTimeSlots", TimeSlotRow));
  });

  const readSpaceOptions = Effect.fn("SessionStore.readSpaceOptions")(
    function* readSpaceOptions(sessionId: SessionId) {
      const valid = yield* decodeInput(
        "SessionStore.readSpaceOptions",
        SessionId
      )(sessionId);

      return yield* sql`
      SELECT sp.id AS id, sp.name AS name, COALESCE(pp.name, '') AS "group"
      FROM space sp LEFT JOIN space pp ON pp.id = sp.parent_id
      WHERE sp.event_id = (SELECT event_id FROM session WHERE id = ${valid})
        AND NOT EXISTS (SELECT 1 FROM space ch WHERE ch.parent_id = sp.id)
      ORDER BY sp."order", sp.name, sp.id
      LIMIT ${ROW_BUDGET.eventSpaces}
    `.pipe(decodeRows("SessionStore.readSpaceOptions", SpaceOption));
    }
  );

  const facilitatorsBySession = Effect.fn("SessionStore.facilitatorsBySession")(
    function* facilitatorsBySession(sessionIds: readonly SessionId[]) {
      const ids = yield* decodeInput(
        "SessionStore.facilitatorsBySession",
        Schema.Array(SessionId)
      )(sessionIds);

      const result = new Map<SessionId, Facilitator[]>(
        ids.map((id) => [id, []])
      );

      if (ids.length === 0) {
        return result;
      }

      const rows = yield* sql`
      SELECT sf.session_id AS sessionId, ${sql.literal(FACILITATOR_COLUMNS)}
      FROM session_facilitators sf
      JOIN facilitator f ON f.id = sf.facilitator_id
      LEFT JOIN user o ON o.id = f.organizer_id
      WHERE ${sql.in("sf.session_id", ids)} AND f.deleted_at IS NULL
      ORDER BY f.display_name, f.id
      LIMIT ${ROW_BUDGET.panelFacilitators}
    `.pipe(
        decodeRows(
          "SessionStore.facilitatorsBySession",
          FacilitatorBySessionRow
        )
      );

      for (const { sessionId, ...facilitator } of rows) {
        result.get(sessionId)?.push(facilitator);
      }

      return result;
    }
  );

  const saveFieldValues = Effect.fn("SessionStore.saveFieldValues")(
    function* saveFieldValues(options: typeof FieldValuesInput.Type) {
      const input = yield* decodeInput(
        "SessionStore.saveFieldValues",
        FieldValuesInput
      )(options);

      if (input.values.length === 0) {
        return;
      }

      const now = toSqlDateTime(yield* DateTime.now);
      yield* sql`
      INSERT INTO session_field_value ${sql.insert(
        input.values.map((value) => ({
          creation_time: now,
          field_id: value.fieldId,
          modification_time: now,
          session_id: input.sessionId,
          value: pythonJson(value.value),
        }))
      )}
      ON CONFLICT (session_id, field_id) DO UPDATE SET value = excluded.value
    `.pipe(storeFailure("SessionStore.saveFieldValues"));
    }
  );

  const readFieldValues = Effect.fn("SessionStore.readFieldValues")(
    function* readFieldValues(sessionId: SessionId) {
      const valid = yield* decodeInput(
        "SessionStore.readFieldValues",
        SessionId
      )(sessionId);

      const rows = yield* sql`
      SELECT ${sql.literal(FIELD_ANSWER_COLUMNS)}
      FROM session_field_value v JOIN session_field f ON f.id = v.field_id
      WHERE v.session_id = ${valid}
      ORDER BY f."order", f.name, v.id
      LIMIT ${ROW_BUDGET.eventFields}
    `.pipe(decodeRows("SessionStore.readFieldValues", FieldAnswerRow));

      return rows.map(answerOf);
    }
  );

  const countByTrack = Effect.fn("SessionStore.countByTrack")(
    function* countByTrack(eventId: EventId) {
      const valid = yield* decodeInput(
        "SessionStore.countByTrack",
        EventId
      )(eventId);

      return yield* sql`
      SELECT st.track_id AS trackId,
        COUNT(DISTINCT CASE WHEN s.status = 'pending' THEN s.id END) AS pending,
        COUNT(DISTINCT CASE WHEN s.status = 'accepted' THEN s.id END) AS accepted,
        COUNT(DISTINCT CASE WHEN s.status = 'accepted'
          AND EXISTS (SELECT 1 FROM agenda_item ca WHERE ca.session_id = s.id) THEN s.id END) AS scheduled,
        COUNT(DISTINCT CASE WHEN s.status = 'on_hold' THEN s.id END) AS onHold,
        COUNT(DISTINCT CASE WHEN s.status = 'rejected' THEN s.id END) AS rejected
      FROM session s
      JOIN proposal_category c ON c.id = s.category_id
      JOIN session_tracks st ON st.session_id = s.id
      WHERE c.event_id = ${valid} AND s.deleted_at IS NULL
      GROUP BY st.track_id
      ORDER BY st.track_id
      LIMIT ${ROW_BUDGET.eventTracks}
    `.pipe(decodeRows("SessionStore.countByTrack", CountsRow));
    }
  );

  return SessionStore.of({
    countByTrack,
    create,
    facilitatorsBySession,
    listByEvent,
    listByFacilitator,
    listDeletedByEvent,
    listProposalCards,
    listScheduledCards,
    read,
    readFieldValues,
    readInEvent,
    readPreferredTimeSlots,
    readScheduledCard,
    readSpaceOptions,
    readTrackIds,
    restore,
    saveFieldValues,
    setFacilitators,
    setTimeSlots,
    setTracks,
    slugExists,
    softDelete,
    update,
  });
});

export const SessionStoreLive = Layer.effect(SessionStore, makeSessionStore);
