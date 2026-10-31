import { ParticipationStatus } from "@zagrajmy/core";
import type {
  AgendaSlot,
  LockedSession,
  PersonFace,
  SessionContext,
  SessionSeatCounts,
} from "@zagrajmy/core/enrollment/api";
import { HouseholdSeat, RosterPerson } from "@zagrajmy/core/enrollment/api";
import { EnrollmentWrite } from "@zagrajmy/core/enrollment/enroll";
import { EnrollmentStore } from "@zagrajmy/core/enrollment/ports";
import { EnrollmentWindowRules } from "@zagrajmy/core/enrollment/schemas";
import { DateTime, Effect, Layer, Match, Option, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";

import { asEnrollmentFailure } from "./enrollment-errors.js";
import {
  decodeFirst,
  decodeInput,
  decodeRows,
  IdRow,
  SqlBool,
  SqlDateTime,
  toSqlDateTime,
} from "./rows.js";
import {
  lockSeatHoldersStatement,
  lockSessionRowStatement,
} from "./seat-locks.js";
import { seatsQuery } from "./seats.js";
import { SeatsRow } from "./shared-rows.js";
import { PUBLIC_SCHEDULED_SESSION, ROW_BUDGET } from "./sql-fragments.js";

export const WindowRow = Schema.Struct({
  ...EnrollmentWindowRules.fields,
  allowAnonymousEnrollment: SqlBool,
  endTime: SqlDateTime,
  limitToEndTime: SqlBool,
  restrictToConfiguredUsers: SqlBool,
  startTime: SqlDateTime,
});

export const WINDOW_COLUMNS = `
  ec.id AS pk, ec.start_time AS startTime, ec.end_time AS endTime,
  ec.percentage_slots AS percentageSlots, ec.limit_to_end_time AS limitToEndTime,
  ec.max_waitlist_sessions AS maxWaitlistSessions,
  ec.restrict_to_configured_users AS restrictToConfiguredUsers,
  ec.allow_anonymous_enrollment AS allowAnonymousEnrollment`;

const HeadRow = Schema.Struct({
  agendaEnd: Schema.NullOr(SqlDateTime),
  agendaStart: Schema.NullOr(SqlDateTime),
  description: Schema.String,
  eventCoverImage: Schema.String,
  eventId: Schema.Int,
  eventName: Schema.String,
  eventSlug: Schema.String,
  facilitatorName: Schema.String,
  isPubliclyScheduled: SqlBool,
  minAge: Schema.Int,
  participantsLimit: Schema.Int,
  presenterAvatarUrl: Schema.NullOr(Schema.String),
  presenterEmail: Schema.NullOr(Schema.String),
  presenterId: Schema.NullOr(Schema.Int),
  presenterName: Schema.NullOr(Schema.String),
  presenterUseGravatar: Schema.NullOr(SqlBool),
  sessionCoverImage: Schema.String,
  sessionId: Schema.Int,
  spaceName: Schema.NullOr(Schema.String),
  title: Schema.String,
  viewerBanned: SqlBool,
  viewerGuestCount: Schema.Int,
  viewerHasParticipation: SqlBool,
  viewerShadowbanned: SqlBool,
});

const PersonRow = Schema.Struct({
  ...RosterPerson.fields,
  isActive: SqlBool,
  useGravatar: SqlBool,
});

const SeatRow = Schema.Struct({
  ...HouseholdSeat.fields,
  endTime: Schema.NullOr(SqlDateTime),
  hasAgenda: SqlBool,
  startTime: Schema.NullOr(SqlDateTime),
});

const UserIdRow = Schema.Struct({ id: Schema.Int });

const ParticipationRow = Schema.Struct({
  status: ParticipationStatus,
  userId: Schema.Int,
});

const LockHeadRow = Schema.Struct({
  eventId: Schema.Int,
  eventSlug: Schema.String,
  participantsLimit: Schema.Int,
  presenterId: Schema.NullOr(Schema.Int),
  title: Schema.String,
});

const ContextInput = Schema.Struct({
  now: Schema.DateTimeUtc,
  sessionId: Schema.Int,
  sphereId: Schema.Int,
  viewerId: Schema.Int,
});

const UserIds = Schema.Array(Schema.Int);

const EventUsersInput = Schema.Struct({
  eventId: Schema.Int,
  userIds: UserIds,
});

const ConflictInput = Schema.Struct({
  sessionId: Schema.Int,
  userIds: UserIds,
});

const LockInput = Schema.Struct({
  householdUserIds: UserIds,
  now: Schema.DateTimeUtc,
  sessionId: Schema.Int,
  viewerId: Schema.Int,
});

const ApplyInput = Schema.Struct({
  guestName: Schema.String,
  sessionId: Schema.Int,
  viewerId: Schema.Int,
  writes: Schema.Array(EnrollmentWrite),
});

const WINDOW_BUDGET = 200;

const PERSON_COLUMNS = `
  u.id AS id, u.name AS name, u.email AS email, u.slug AS slug,
  u.avatar_url AS avatarUrl, u.use_gravatar AS useGravatar, u.is_active AS isActive`;

const randomSuffix = (): string =>
  [...crypto.getRandomValues(new Uint8Array(8))]
    .map((byte) => byte.toString(36).padStart(2, "0"))
    .join("")
    .slice(0, 11);

export const makeEnrollmentStore = Effect.gen(function* makeEnrollmentStore() {
  const sql = yield* SqlClient;

  const seatCounts = (options: {
    readonly sessionId: number;
    readonly now: DateTime.Utc;
    readonly operation: string;
  }) =>
    seatsQuery({
      limit: 1,
      now: toSqlDateTime(options.now),
      sql,
      where: sql`s.id = ${options.sessionId}`,
    }).pipe(
      decodeFirst(options.operation, SeatsRow),
      Effect.map(
        Option.map((row): SessionSeatCounts => ({
          effectiveParticipantsLimit: row.effectiveParticipantsLimit,
          eligibleWindowIds: row.eligibleWindowIds,
          enrolledCount: row.enrolledCount,
          isFull: row.isFull,
          seatsLeft: row.seatsLeft,
          waitingCount: row.waitingCount,
        }))
      )
    );

  const windowsOf = (eventId: number, operation: string) =>
    sql`SELECT ${sql.literal(WINDOW_COLUMNS)} FROM enrollment_config ec
        WHERE ec.event_id = ${eventId} ORDER BY ec.id LIMIT ${WINDOW_BUDGET}`.pipe(
      decodeRows(operation, WindowRow)
    );

  const conflicted = (options: {
    readonly sessionId: number;
    readonly userIds: readonly number[];
    readonly operation: string;
  }) =>
    options.userIds.length === 0
      ? Effect.succeed([])
      : sql`
      SELECT DISTINCT p.user_id AS id
      FROM agenda_item me
      JOIN session mine ON mine.id = me.session_id
      JOIN session other ON other.event_id = mine.event_id AND other.id <> mine.id AND other.deleted_at IS NULL
      JOIN agenda_item oa ON oa.session_id = other.id
      JOIN session_participant p ON p.session_id = other.id AND p.status IN ('confirmed', 'offered')
      WHERE me.session_id = ${options.sessionId}
        AND ${sql.in("p.user_id", options.userIds)}
        AND oa.start_time < me.end_time AND oa.end_time > me.start_time
      ORDER BY p.user_id
      LIMIT ${options.userIds.length}
    `.pipe(
          decodeRows(options.operation, UserIdRow),
          Effect.map((rows) => rows.map((row) => row.id))
        );

  const readSessionContext = Effect.fn("EnrollmentStore.readSessionContext")(
    function* readSessionContext(query: typeof ContextInput.Type) {
      const operation = "EnrollmentStore.readSessionContext";
      const input = yield* decodeInput(operation, ContextInput)(query);

      const head = yield* sql`
      SELECT s.id AS sessionId, s.title AS title, s.description AS description,
        s.facilitator_name AS facilitatorName, s.min_age AS minAge,
        s.participants_limit AS participantsLimit, s.presenter_id AS presenterId,
        s.cover_image AS sessionCoverImage,
        e.id AS eventId, e.slug AS eventSlug, e.name AS eventName, e.cover_image AS eventCoverImage,
        a.start_time AS agendaStart, a.end_time AS agendaEnd, sp.name AS spaceName,
        (${sql.literal(PUBLIC_SCHEDULED_SESSION)}) AS isPubliclyScheduled,
        EXISTS (SELECT 1 FROM session_participant vp WHERE vp.session_id = s.id AND vp.user_id = ${input.viewerId}) AS viewerHasParticipation,
        EXISTS (SELECT 1 FROM event_ban b WHERE b.event_id = e.id AND b.user_id = ${input.viewerId}) AS viewerBanned,
        (s.presenter_id IS NOT NULL AND EXISTS (
          SELECT 1 FROM shadowban sb WHERE sb.owner_id = s.presenter_id AND sb.target_id = ${input.viewerId})) AS viewerShadowbanned,
        (SELECT COUNT(*) FROM session_participant gp JOIN user gu ON gu.id = gp.user_id
          WHERE gp.session_id = s.id AND gp.enrolled_by_id = ${input.viewerId} AND gu.user_type = 'anonymous') AS viewerGuestCount,
        pu.name AS presenterName, pu.email AS presenterEmail, pu.avatar_url AS presenterAvatarUrl,
        pu.use_gravatar AS presenterUseGravatar
      FROM session s
      JOIN event e ON e.id = s.event_id
      LEFT JOIN agenda_item a ON a.session_id = s.id
      LEFT JOIN space sp ON sp.id = a.space_id
      LEFT JOIN user pu ON pu.id = s.presenter_id
      WHERE s.id = ${input.sessionId} AND e.sphere_id = ${input.sphereId} AND s.deleted_at IS NULL
    `.pipe(decodeFirst(operation, HeadRow));

      if (Option.isNone(head)) {
        return Option.none<SessionContext>();
      }

      const row = head.value;

      const seats = yield* seatCounts({
        now: input.now,
        operation,
        sessionId: row.sessionId,
      });

      const windows = yield* windowsOf(row.eventId, operation);

      const agenda: AgendaSlot | null =
        row.agendaStart === null || row.agendaEnd === null
          ? null
          : {
              endTime: row.agendaEnd,
              spaceName: row.spaceName,
              startTime: row.agendaStart,
            };

      const presenter: PersonFace | null =
        row.presenterId === null
          ? null
          : {
              avatarUrl: row.presenterAvatarUrl ?? "",
              email: row.presenterEmail ?? "",
              name: row.presenterName ?? "",
              useGravatar: row.presenterUseGravatar ?? false,
            };

      const context: SessionContext = {
        agenda,
        description: row.description,
        eventCoverImage: row.eventCoverImage,
        eventId: row.eventId,
        eventName: row.eventName,
        eventSlug: row.eventSlug,
        facilitatorName: row.facilitatorName,
        isPubliclyScheduled: row.isPubliclyScheduled,
        minAge: row.minAge,
        participantsLimit: row.participantsLimit,
        presenter,
        presenterId: row.presenterId,
        seats: Option.getOrElse(seats, () => ({
          effectiveParticipantsLimit: 0,
          eligibleWindowIds: [],
          enrolledCount: 0,
          isFull: false,
          seatsLeft: 0,
          waitingCount: 0,
        })),
        sessionCoverImage: row.sessionCoverImage,
        sessionId: row.sessionId,
        title: row.title,
        viewerBanned: row.viewerBanned,
        viewerGuestCount: row.viewerGuestCount,
        viewerHasParticipation: row.viewerHasParticipation,
        viewerShadowbanned: row.viewerShadowbanned,
        windows,
      };

      return Option.some(context);
    }
  );

  const readPeople = Effect.fn("EnrollmentStore.readPeople")(
    function* readPeople(userIds: readonly number[]) {
      const operation = "EnrollmentStore.readPeople";
      const ids = yield* decodeInput(operation, UserIds)(userIds);

      if (ids.length === 0) {
        return [];
      }

      const rows = yield* sql`SELECT ${sql.literal(PERSON_COLUMNS)} FROM user u
      WHERE ${sql.in("u.id", ids)} LIMIT ${ids.length}`.pipe(
        decodeRows(operation, PersonRow)
      );

      const byId = new Map(rows.map((row) => [row.id, row]));

      return ids.flatMap((id) => {
        const person = byId.get(id);

        return person === undefined ? [] : [person];
      });
    }
  );

  const householdSeats = Effect.fn("EnrollmentStore.householdSeats")(
    function* householdSeats(query: typeof EventUsersInput.Type) {
      const operation = "EnrollmentStore.householdSeats";
      const input = yield* decodeInput(operation, EventUsersInput)(query);

      if (input.userIds.length === 0) {
        return [];
      }

      return yield* sql`
      SELECT p.user_id AS userId, p.session_id AS sessionId, p.status AS status,
        a.start_time AS startTime, a.end_time AS endTime, (a.id IS NOT NULL) AS hasAgenda
      FROM session_participant p
      JOIN session s ON s.id = p.session_id
      LEFT JOIN agenda_item a ON a.session_id = s.id
      WHERE s.event_id = ${input.eventId} AND ${sql.in("p.user_id", input.userIds)}
      ORDER BY p.creation_time, p.id
      LIMIT ${ROW_BUDGET.participationsPerSession}
    `.pipe(decodeRows(operation, SeatRow));
    }
  );

  const conflictedUserIds = Effect.fn("EnrollmentStore.conflictedUserIds")(
    function* conflictedUserIds(query: typeof ConflictInput.Type) {
      const operation = "EnrollmentStore.conflictedUserIds";
      const input = yield* decodeInput(operation, ConflictInput)(query);

      return yield* conflicted({ ...input, operation });
    }
  );

  const readSeatState = Effect.fn("EnrollmentStore.readSeatState")(
    function* readSeatState(request: typeof LockInput.Type) {
      const operation = "EnrollmentStore.readSeatState";
      const input = yield* decodeInput(operation, LockInput)(request);

      const head = yield* sql`
      SELECT s.participants_limit AS participantsLimit, s.presenter_id AS presenterId,
        s.title AS title, s.event_id AS eventId, e.slug AS eventSlug
      FROM session s JOIN event e ON e.id = s.event_id
      WHERE s.id = ${input.sessionId} AND s.deleted_at IS NULL
    `.pipe(decodeFirst(operation, LockHeadRow));

      if (Option.isNone(head)) {
        return Option.none<LockedSession>();
      }

      const seats = yield* seatCounts({
        now: input.now,
        operation,
        sessionId: input.sessionId,
      });

      const windows = yield* windowsOf(head.value.eventId, operation);

      const eligibleIds = Option.match(seats, {
        onNone: (): readonly number[] => [],
        onSome: (found) => found.eligibleWindowIds,
      });

      const participations = yield* sql`
      SELECT p.user_id AS userId, p.status AS status FROM session_participant p
      WHERE p.session_id = ${input.sessionId}
      ORDER BY p.creation_time, p.id LIMIT ${ROW_BUDGET.participationsPerSession}
    `.pipe(decodeRows(operation, ParticipationRow));

      const guests = yield* sql`
      SELECT p.id AS id FROM session_participant p JOIN user u ON u.id = p.user_id
      WHERE p.session_id = ${input.sessionId} AND p.enrolled_by_id = ${input.viewerId}
        AND u.user_type = 'anonymous'
      ORDER BY p.id LIMIT ${ROW_BUDGET.participationsPerSession}
    `.pipe(decodeRows(operation, IdRow));

      const shadowbanned =
        head.value.presenterId === null
          ? []
          : yield* sql`SELECT target_id AS id FROM shadowban WHERE owner_id = ${head.value.presenterId}
              ORDER BY target_id LIMIT ${ROW_BUDGET.bans}`.pipe(
              decodeRows(operation, UserIdRow)
            );

      const locked: LockedSession = {
        conflictedUserIds: yield* conflicted({
          operation,
          sessionId: input.sessionId,
          userIds: input.householdUserIds,
        }),
        eligibleWindows: windows.filter((window) =>
          eligibleIds.includes(window.pk)
        ),
        enrolledCount: Option.match(seats, {
          onNone: () => 0,
          onSome: (found) => found.enrolledCount,
        }),
        eventId: head.value.eventId,
        eventSlug: head.value.eventSlug,
        guestParticipationIds: guests.map((guest) => guest.id),
        participantsLimit: head.value.participantsLimit,
        participations: participations.filter((row) =>
          input.householdUserIds.includes(row.userId)
        ),
        presenterId: head.value.presenterId,
        shadowbannedUserIds: shadowbanned.map((row) => row.id),
        title: head.value.title,
      };

      return Option.some(locked);
    }
  );

  const lockSessionRow = Effect.fn("EnrollmentStore.lockSessionRow")(
    function* lockSessionRow(sessionId: number) {
      const operation = "EnrollmentStore.lockSessionRow";
      const id = yield* decodeInput(operation, Schema.Int)(sessionId);

      const rows = yield* lockSessionRowStatement(sql, id).pipe(
        decodeRows(operation, IdRow)
      );

      return rows.length > 0;
    }
  );

  const lockSeatHolders = Effect.fn("EnrollmentStore.lockSeatHolders")(
    function* lockSeatHolders(userIds: readonly number[]) {
      const operation = "EnrollmentStore.lockSeatHolders";
      const ids = [...new Set(yield* decodeInput(operation, UserIds)(userIds))];

      if (ids.length > 0) {
        yield* lockSeatHoldersStatement(sql, ids).pipe(
          decodeRows(operation, IdRow)
        );
      }
    }
  );

  const apply = Effect.fn("EnrollmentStore.apply")(function* apply(
    batch: typeof ApplyInput.Type
  ) {
    const operation = "EnrollmentStore.apply";
    const input = yield* decodeInput(operation, ApplyInput)(batch);
    const now = toSqlDateTime(yield* DateTime.now);

    const insertSeat = (seat: {
      readonly userId: number;
      readonly status: string;
      readonly partyId: number | null;
      readonly enrolledById: number | null;
    }) =>
      sql`INSERT INTO session_participant ${sql.insert({
        claim_token: "",
        claimed_at: null,
        creation_time: now,
        enrolled_by_id: seat.enrolledById,
        modification_time: now,
        offer_expires_at: null,
        offered_at: null,
        party_id: seat.partyId,
        session_id: input.sessionId,
        status: seat.status,
        user_id: seat.userId,
      })}`;

    const addGuest = (partyId: number | null) =>
      Effect.gen(function* insertGuest() {
        const suffix = randomSuffix();

        const [guest] = yield* sql`INSERT INTO user ${sql.insert({
          age_band: "unknown",
          avatar_url: "",
          claim_token: "",
          date_joined: now,
          discord_username: "",
          email: "",
          email_verification_sent_at: null,
          email_verified: 0,
          is_active: 0,
          is_staff: 0,
          is_superuser: 0,
          last_login: null,
          manager_id: null,
          name: input.guestName,
          password: "",
          pending_email: "",
          privacy_revision: "",
          slug: `guest-${suffix}`,
          use_gravatar: 0,
          user_type: "anonymous",
          username: `anon_${suffix}`,
        })} RETURNING id`.pipe(decodeRows(operation, IdRow));

        if (guest !== undefined) {
          yield* sql`${insertSeat({
            enrolledById: input.viewerId,
            partyId,
            status: "confirmed",
            userId: guest.id,
          })} RETURNING id`.pipe(decodeRows(operation, IdRow));
        }
      });

    const writeOne = (write: EnrollmentWrite) =>
      Match.value(write).pipe(
        Match.tagsExhaustive({
          AddGuests: ({ count, partyId }) =>
            Effect.all(
              Array.from({ length: count }, () => addGuest(partyId)),
              { discard: true }
            ),
          Delete: ({ userId }) =>
            sql`DELETE FROM session_participant
              WHERE session_id = ${input.sessionId} AND user_id = ${userId} RETURNING id`.pipe(
              decodeRows(operation, IdRow),
              Effect.asVoid
            ),
          HoldSeat: () => Effect.void,
          RemoveGuest: ({ participationId }) =>
            Effect.all(
              [
                sql`DELETE FROM user WHERE user_type = 'anonymous' AND id IN (
                  SELECT user_id FROM session_participant
                  WHERE id = ${participationId} AND session_id = ${input.sessionId}
                    AND enrolled_by_id = ${input.viewerId})
                RETURNING id`.pipe(decodeRows(operation, IdRow)),
                sql`DELETE FROM session_participant WHERE id = ${participationId}
                  AND session_id = ${input.sessionId} RETURNING id`.pipe(
                  decodeRows(operation, IdRow)
                ),
              ],
              { discard: true }
            ),
          Save: ({ partyId, status, userId }) =>
            sql`${insertSeat({ enrolledById: null, partyId, status, userId })}
              ON CONFLICT (session_id, user_id) DO UPDATE SET
                status = excluded.status, party_id = excluded.party_id,
                modification_time = excluded.modification_time
              RETURNING id`.pipe(decodeRows(operation, IdRow), Effect.asVoid),
        })
      );

    yield* Effect.all(
      input.writes.map((write) => writeOne(write)),
      {
        discard: true,
      }
    );
  });

  const occupyingUserIds = Effect.fn("EnrollmentStore.occupyingUserIds")(
    function* occupyingUserIds(query: typeof EventUsersInput.Type) {
      const operation = "EnrollmentStore.occupyingUserIds";
      const input = yield* decodeInput(operation, EventUsersInput)(query);

      if (input.userIds.length === 0) {
        return [];
      }

      const rows = yield* sql`
      SELECT DISTINCT p.user_id AS id FROM session_participant p JOIN session s ON s.id = p.session_id
      WHERE s.event_id = ${input.eventId} AND p.status IN ('confirmed', 'offered')
        AND ${sql.in("p.user_id", input.userIds)}
      ORDER BY p.user_id LIMIT ${input.userIds.length}
    `.pipe(decodeRows(operation, UserIdRow));

      return rows.map((row) => row.id);
    }
  );

  const fail = asEnrollmentFailure;

  return EnrollmentStore.of({
    apply: (batch) => apply(batch).pipe(fail("EnrollmentStore.apply")),
    conflictedUserIds: (query) =>
      conflictedUserIds(query).pipe(fail("EnrollmentStore.conflictedUserIds")),
    householdSeats: (query) =>
      householdSeats(query).pipe(fail("EnrollmentStore.householdSeats")),
    lockSeatHolders: (userIds) =>
      lockSeatHolders(userIds).pipe(fail("EnrollmentStore.lockSeatHolders")),
    lockSessionRow: (sessionId) =>
      lockSessionRow(sessionId).pipe(fail("EnrollmentStore.lockSessionRow")),
    occupyingUserIds: (query) =>
      occupyingUserIds(query).pipe(fail("EnrollmentStore.occupyingUserIds")),
    readPeople: (userIds) =>
      readPeople(userIds).pipe(fail("EnrollmentStore.readPeople")),
    readSeatState: (request) =>
      readSeatState(request).pipe(fail("EnrollmentStore.readSeatState")),
    readSessionContext: (query) =>
      readSessionContext(query).pipe(
        fail("EnrollmentStore.readSessionContext")
      ),
  });
});

export const EnrollmentStoreLive = Layer.effect(
  EnrollmentStore,
  makeEnrollmentStore
);
