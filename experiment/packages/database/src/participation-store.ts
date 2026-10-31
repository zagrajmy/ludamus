import {
  EventId,
  EventParticipationScope,
  GuestSeat,
  HeldSeat,
  OfferTerms,
  Participation,
  ParticipationId,
  ParticipationStatus,
  ParticipationStore,
  SeatRequest,
  SessionId,
  StoreError,
  UserId,
} from "@zagrajmy/core";
import type { OfferedParty } from "@zagrajmy/core";
import { DateTime, Effect, Layer, Option, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";
import type { Fragment } from "effect/sql/Statement";

import {
  decodeFirst,
  decodeInput,
  decodeRows,
  IdRow,
  SqlDateTime,
  toSqlDateTime,
} from "./rows.js";
import { seatsQuery } from "./seats.js";
import { SeatsRow } from "./shared-rows.js";
import { OCCUPYING, ROW_BUDGET } from "./sql-fragments.js";

const ParticipationRow = Schema.Struct({
  ...Participation.fields,
  claimedAt: Schema.NullOr(SqlDateTime),
  creationTime: SqlDateTime,
  modificationTime: SqlDateTime,
  offerExpiresAt: Schema.NullOr(SqlDateTime),
  offeredAt: Schema.NullOr(SqlDateTime),
});

const TimedRow = Schema.Struct({
  ...ParticipationRow.fields,
  agendaEndTime: Schema.NullOr(SqlDateTime),
  agendaStartTime: Schema.NullOr(SqlDateTime),
});

const PARTICIPATION_COLUMNS = `
  p.id AS id, p.session_id AS sessionId, p.user_id AS userId, p.party_id AS partyId,
  p.enrolled_by_id AS enrolledById, p.status AS status,
  p.creation_time AS creationTime, p.modification_time AS modificationTime,
  p.offered_at AS offeredAt, p.offer_expires_at AS offerExpiresAt,
  p.claim_token AS claimToken, p.claimed_at AS claimedAt`;

const UserIdRow = Schema.Struct({ id: UserId });

const ParticipationIdRow = Schema.Struct({ id: ParticipationId });

const StatusRow = Schema.Struct({ status: ParticipationStatus });

const OfferHeadRow = Schema.Struct({
  eventSlug: Schema.String,
  sessionId: SessionId,
  sessionTitle: Schema.String,
});

const EventIdRow = Schema.Struct({ eventId: EventId });

const SeatsInput = Schema.Struct({
  now: Schema.DateTimeUtc,
  sessionIds: Schema.Array(SessionId),
});

const ConflictInput = Schema.Struct({
  sessionId: SessionId,
  userIds: Schema.Array(UserId),
});

const GuestsInput = Schema.Struct({
  enrolledById: UserId,
  sessionId: SessionId,
});

const SeatKeyInput = Schema.Struct({ sessionId: SessionId, userId: UserId });

const OfferInput = Schema.Struct({
  ids: Schema.Array(ParticipationId),
  terms: OfferTerms,
});

const ClaimInput = Schema.Struct({
  claimedAt: Schema.DateTimeUtc,
  ids: Schema.Array(ParticipationId),
});

const PartyInput = Schema.Struct({
  claimToken: Schema.String,
  sessionId: SessionId,
});

const Ids = Schema.Array(ParticipationId);

export const makeParticipationStore = Effect.gen(
  function* makeParticipationStore() {
    const sql = yield* SqlClient;
    const columns = sql.literal(PARTICIPATION_COLUMNS);

    const readWhere = (operation: string, where: Fragment) =>
      sql`SELECT ${columns} FROM session_participant p WHERE ${where} ORDER BY p.creation_time, p.id
        LIMIT ${ROW_BUDGET.participationsPerSession}`.pipe(
        decodeRows(operation, ParticipationRow)
      );

    const readKey = (operation: string, sessionId: SessionId, userId: UserId) =>
      sql`SELECT ${columns} FROM session_participant p WHERE p.session_id = ${sessionId} AND p.user_id = ${userId}`.pipe(
        decodeFirst(operation, ParticipationRow)
      );

    const requireKey = (
      operation: string,
      sessionId: SessionId,
      userId: UserId
    ) =>
      readKey(operation, sessionId, userId).pipe(
        Effect.flatMap(
          Option.match({
            onNone: () =>
              Effect.fail(
                new StoreError({ operation, reason: "written row vanished" })
              ),
            onSome: Effect.succeed,
          })
        )
      );

    const seats = Effect.fn("ParticipationStore.seats")(function* seats(
      options: typeof SeatsInput.Type
    ) {
      const input = yield* decodeInput(
        "ParticipationStore.seats",
        SeatsInput
      )(options);

      if (input.sessionIds.length === 0) {
        return [];
      }

      return yield* seatsQuery({
        limit: input.sessionIds.length,
        now: toSqlDateTime(input.now),
        sql,
        where: sql`s.deleted_at IS NULL AND ${sql.in("s.id", input.sessionIds)}`,
      }).pipe(decodeRows("ParticipationStore.seats", SeatsRow));
    });

    const listForSession = Effect.fn("ParticipationStore.listForSession")(
      function* listForSession(sessionId: SessionId) {
        const valid = yield* decodeInput(
          "ParticipationStore.listForSession",
          SessionId
        )(sessionId);

        return yield* readWhere(
          "ParticipationStore.listForSession",
          sql`p.session_id = ${valid}`
        );
      }
    );

    const listForUsersInEvent = Effect.fn(
      "ParticipationStore.listForUsersInEvent"
    )(function* listForUsersInEvent(
      scope: typeof EventParticipationScope.Type
    ) {
      const input = yield* decodeInput(
        "ParticipationStore.listForUsersInEvent",
        EventParticipationScope
      )(scope);

      if (input.userIds.length === 0) {
        return [];
      }

      return yield* sql`
      SELECT ${columns}, a.start_time AS agendaStartTime, a.end_time AS agendaEndTime
      FROM session_participant p
      JOIN session s ON s.id = p.session_id
      LEFT JOIN agenda_item a ON a.session_id = s.id
      WHERE s.event_id = ${input.eventId} AND ${sql.in("p.user_id", input.userIds)}
      ORDER BY p.creation_time, p.id
      LIMIT ${ROW_BUDGET.participationsPerSession}
    `.pipe(decodeRows("ParticipationStore.listForUsersInEvent", TimedRow));
    });

    const occupyingUserIds = Effect.fn("ParticipationStore.occupyingUserIds")(
      function* occupyingUserIds(scope: typeof EventParticipationScope.Type) {
        const input = yield* decodeInput(
          "ParticipationStore.occupyingUserIds",
          EventParticipationScope
        )(scope);

        if (input.userIds.length === 0) {
          return [];
        }

        const rows = yield* sql`
      SELECT DISTINCT p.user_id AS id FROM session_participant p JOIN session s ON s.id = p.session_id
      WHERE s.event_id = ${input.eventId} AND p.status IN ${sql.literal(OCCUPYING)}
        AND ${sql.in("p.user_id", input.userIds)}
      ORDER BY p.user_id
      LIMIT ${input.userIds.length}
    `.pipe(decodeRows("ParticipationStore.occupyingUserIds", UserIdRow));

        return rows.map((row) => row.id);
      }
    );

    const conflictedUserIds = Effect.fn("ParticipationStore.conflictedUserIds")(
      function* conflictedUserIds(options: typeof ConflictInput.Type) {
        const input = yield* decodeInput(
          "ParticipationStore.conflictedUserIds",
          ConflictInput
        )(options);

        if (input.userIds.length === 0) {
          return [];
        }

        const rows = yield* sql`
      SELECT DISTINCT p.user_id AS id
      FROM agenda_item me
      JOIN session mine ON mine.id = me.session_id
      JOIN session other ON other.event_id = mine.event_id AND other.id <> mine.id AND other.deleted_at IS NULL
      JOIN agenda_item oa ON oa.session_id = other.id
      JOIN session_participant p ON p.session_id = other.id AND p.status IN ('confirmed', 'offered')
      WHERE me.session_id = ${input.sessionId}
        AND ${sql.in("p.user_id", input.userIds)}
        AND oa.start_time < me.end_time AND oa.end_time > me.start_time
      ORDER BY p.user_id
      LIMIT ${input.userIds.length}
    `.pipe(decodeRows("ParticipationStore.conflictedUserIds", UserIdRow));

        return rows.map((row) => row.id);
      }
    );

    const guestsEnrolledBy = Effect.fn("ParticipationStore.guestsEnrolledBy")(
      function* guestsEnrolledBy(options: typeof GuestsInput.Type) {
        const input = yield* decodeInput(
          "ParticipationStore.guestsEnrolledBy",
          GuestsInput
        )(options);

        return yield* readWhere(
          "ParticipationStore.guestsEnrolledBy",
          sql`p.session_id = ${input.sessionId} AND p.enrolled_by_id = ${input.enrolledById}`
        );
      }
    );

    const insertSeat = (options: {
      readonly sessionId: SessionId;
      readonly userId: UserId;
      readonly status: ParticipationStatus;
      readonly partyId: number | null;
      readonly enrolledById: number | null;
      readonly now: string;
      readonly offer: typeof OfferTerms.Type | null;
    }) =>
      sql`INSERT INTO session_participant ${sql.insert({
        claim_token: options.offer?.claimToken ?? "",
        claimed_at: null,
        creation_time: options.now,
        enrolled_by_id: options.enrolledById,
        modification_time: options.now,
        offer_expires_at:
          options.offer === null
            ? null
            : toSqlDateTime(options.offer.offerExpiresAt),
        offered_at:
          options.offer === null
            ? null
            : toSqlDateTime(options.offer.offeredAt),
        party_id: options.partyId,
        session_id: options.sessionId,
        status: options.status,
        user_id: options.userId,
      })}`;

    const upsertSeat = Effect.fn("ParticipationStore.upsertSeat")(
      function* upsertSeat(seat: typeof SeatRequest.Type) {
        const input = yield* decodeInput(
          "ParticipationStore.upsertSeat",
          SeatRequest
        )(seat);

        const now = toSqlDateTime(yield* DateTime.now);
        yield* sql`
      ${insertSeat({ ...input, enrolledById: null, now, offer: null })}
      ON CONFLICT (session_id, user_id) DO UPDATE SET
        status = excluded.status, party_id = excluded.party_id, modification_time = excluded.modification_time
    `.pipe(decodeRows("ParticipationStore.upsertSeat", IdRow));

        return yield* requireKey(
          "ParticipationStore.upsertSeat",
          input.sessionId,
          input.userId
        );
      }
    );

    const createIfAbsent = Effect.fn("ParticipationStore.createIfAbsent")(
      function* createIfAbsent(seat: typeof SeatRequest.Type) {
        const input = yield* decodeInput(
          "ParticipationStore.createIfAbsent",
          SeatRequest
        )(seat);

        const now = toSqlDateTime(yield* DateTime.now);
        yield* sql`
      ${insertSeat({ ...input, enrolledById: null, now, offer: null })}
      ON CONFLICT (session_id, user_id) DO NOTHING
    `.pipe(decodeRows("ParticipationStore.createIfAbsent", IdRow));

        return yield* requireKey(
          "ParticipationStore.createIfAbsent",
          input.sessionId,
          input.userId
        );
      }
    );

    const createGuest = Effect.fn("ParticipationStore.createGuest")(
      function* createGuest(seat: typeof GuestSeat.Type) {
        const input = yield* decodeInput(
          "ParticipationStore.createGuest",
          GuestSeat
        )(seat);

        const now = toSqlDateTime(yield* DateTime.now);
        yield* insertSeat({
          ...input,
          now,
          offer: null,
          status: "confirmed",
        }).pipe(decodeRows("ParticipationStore.createGuest", IdRow));

        return yield* requireKey(
          "ParticipationStore.createGuest",
          input.sessionId,
          input.userId
        );
      }
    );

    const createOffered = Effect.fn("ParticipationStore.createOffered")(
      function* createOffered(seat: typeof HeldSeat.Type) {
        const input = yield* decodeInput(
          "ParticipationStore.createOffered",
          HeldSeat
        )(seat);

        const now = toSqlDateTime(yield* DateTime.now);
        yield* insertSeat({
          ...input,
          enrolledById: null,
          now,
          offer: input,
          status: "offered",
        }).pipe(decodeRows("ParticipationStore.createOffered", IdRow));

        return yield* requireKey(
          "ParticipationStore.createOffered",
          input.sessionId,
          input.userId
        );
      }
    );

    const remove = Effect.fn("ParticipationStore.remove")(function* remove(
      options: typeof SeatKeyInput.Type
    ) {
      const input = yield* decodeInput(
        "ParticipationStore.remove",
        SeatKeyInput
      )(options);

      const rows = yield* sql`
      DELETE FROM session_participant WHERE session_id = ${input.sessionId} AND user_id = ${input.userId}
      RETURNING status
    `.pipe(decodeRows("ParticipationStore.remove", StatusRow));

      return Option.map(Option.fromNullishOr(rows[0]), (row) => row.status);
    });

    const confirm = Effect.fn("ParticipationStore.confirm")(function* confirm(
      ids: readonly ParticipationId[]
    ) {
      const valid = yield* decodeInput("ParticipationStore.confirm", Ids)(ids);

      if (valid.length === 0) {
        return;
      }

      const now = toSqlDateTime(yield* DateTime.now);
      yield* sql`
      UPDATE session_participant SET status = 'confirmed', modification_time = ${now}
      WHERE ${sql.in("id", valid)} RETURNING id
    `.pipe(decodeRows("ParticipationStore.confirm", IdRow));
    });

    const offer = Effect.fn("ParticipationStore.offer")(function* offer(
      options: typeof OfferInput.Type
    ) {
      const input = yield* decodeInput(
        "ParticipationStore.offer",
        OfferInput
      )(options);

      if (input.ids.length === 0) {
        return;
      }

      const now = toSqlDateTime(yield* DateTime.now);
      yield* sql`
      UPDATE session_participant SET ${sql.update({
        claim_token: input.terms.claimToken,
        modification_time: now,
        offer_expires_at: toSqlDateTime(input.terms.offerExpiresAt),
        offered_at: toSqlDateTime(input.terms.offeredAt),
        status: "offered",
      })}
      WHERE ${sql.in("id", input.ids)} RETURNING id
    `.pipe(decodeRows("ParticipationStore.offer", IdRow));
    });

    const markClaimed = Effect.fn("ParticipationStore.markClaimed")(
      function* markClaimed(options: typeof ClaimInput.Type) {
        const input = yield* decodeInput(
          "ParticipationStore.markClaimed",
          ClaimInput
        )(options);

        if (input.ids.length === 0) {
          return 0;
        }

        const now = toSqlDateTime(yield* DateTime.now);

        const rows = yield* sql`
      UPDATE session_participant SET status = 'confirmed', claimed_at = ${toSqlDateTime(input.claimedAt)},
        modification_time = ${now}
      WHERE ${sql.in("id", input.ids)} AND status = 'offered' RETURNING id
    `.pipe(decodeRows("ParticipationStore.markClaimed", IdRow));

        return rows.length;
      }
    );

    const dropOffered = Effect.fn("ParticipationStore.dropOffered")(
      function* dropOffered(ids: readonly ParticipationId[]) {
        const valid = yield* decodeInput(
          "ParticipationStore.dropOffered",
          Ids
        )(ids);

        if (valid.length === 0) {
          return 0;
        }

        const rows = yield* sql`
      DELETE FROM session_participant WHERE ${sql.in("id", valid)} AND status = 'offered' RETURNING id
    `.pipe(decodeRows("ParticipationStore.dropOffered", IdRow));

        return rows.length;
      }
    );

    const offeredParty = (
      operation: string,
      sessionId: SessionId,
      claimToken: string
    ) =>
      Effect.gen(function* readOfferedMembers() {
        const members = yield* readWhere(
          operation,
          sql`p.session_id = ${sessionId} AND p.claim_token = ${claimToken} AND p.status = 'offered'`
        );

        if (members.length === 0) {
          return Option.none<OfferedParty>();
        }

        const head = yield* sql`
        SELECT s.id AS sessionId, s.title AS sessionTitle, e.slug AS eventSlug
        FROM session s JOIN event e ON e.id = s.event_id WHERE s.id = ${sessionId}
      `.pipe(decodeFirst(operation, OfferHeadRow));

        return head.pipe(Option.map((found) => ({ ...found, members })));
      });

    const readOfferedParty = Effect.fn("ParticipationStore.readOfferedParty")(
      function* readOfferedParty(options: typeof PartyInput.Type) {
        const input = yield* decodeInput(
          "ParticipationStore.readOfferedParty",
          PartyInput
        )(options);

        if (input.claimToken === "") {
          return Option.none<OfferedParty>();
        }

        return yield* offeredParty(
          "ParticipationStore.readOfferedParty",
          input.sessionId,
          input.claimToken
        );
      }
    );

    const findOfferByToken = Effect.fn("ParticipationStore.findOfferByToken")(
      function* findOfferByToken(claimToken: string) {
        const token = yield* decodeInput(
          "ParticipationStore.findOfferByToken",
          Schema.String
        )(claimToken);

        if (token === "") {
          return Option.none<OfferedParty>();
        }

        const identity = yield* sql`
      SELECT session_id AS id FROM session_participant WHERE claim_token = ${token} AND status = 'offered'
      ORDER BY id LIMIT 1
    `.pipe(
          decodeFirst(
            "ParticipationStore.findOfferByToken",
            Schema.Struct({ id: SessionId })
          )
        );

        if (Option.isNone(identity)) {
          return Option.none<OfferedParty>();
        }

        return yield* offeredParty(
          "ParticipationStore.findOfferByToken",
          identity.value.id,
          token
        );
      }
    );

    const listLapsedOffers = Effect.fn("ParticipationStore.listLapsedOffers")(
      function* listLapsedOffers(now: DateTime.Utc) {
        const valid = yield* decodeInput(
          "ParticipationStore.listLapsedOffers",
          Schema.DateTimeUtc
        )(now);

        const rows = yield* sql`
      SELECT MIN(id) AS id FROM session_participant
      WHERE status = 'offered' AND offer_expires_at < ${toSqlDateTime(valid)}
      GROUP BY claim_token ORDER BY claim_token LIMIT ${ROW_BUDGET.lapsedOffers}
    `.pipe(
          decodeRows("ParticipationStore.listLapsedOffers", ParticipationIdRow)
        );

        return rows.map((row) => row.id);
      }
    );

    const eventIdOfSession = Effect.fn("ParticipationStore.eventIdOfSession")(
      function* eventIdOfSession(sessionId: SessionId) {
        const valid = yield* decodeInput(
          "ParticipationStore.eventIdOfSession",
          SessionId
        )(sessionId);

        const row =
          yield* sql`SELECT event_id AS eventId FROM session WHERE id = ${valid} AND deleted_at IS NULL`.pipe(
            decodeFirst("ParticipationStore.eventIdOfSession", EventIdRow)
          );

        return row.pipe(Option.map((found) => found.eventId));
      }
    );

    return ParticipationStore.of({
      confirm,
      conflictedUserIds,
      createGuest,
      createIfAbsent,
      createOffered,
      dropOffered,
      eventIdOfSession,
      findOfferByToken,
      guestsEnrolledBy,
      listForSession,
      listForUsersInEvent,
      listLapsedOffers,
      markClaimed,
      occupyingUserIds,
      offer,
      readOfferedParty,
      remove,
      seats,
      upsertSeat,
    });
  }
);

export const ParticipationStoreLive = Layer.effect(
  ParticipationStore,
  makeParticipationStore
);
