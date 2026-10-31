import { PromotionMode } from "@zagrajmy/core";
import { PromotionStore } from "@zagrajmy/core/enrollment/ports";
import { PromotionWrite } from "@zagrajmy/core/enrollment/promotion";
import {
  distinctRecipients,
  ownerSlotsRemaining,
} from "@zagrajmy/core/enrollment/rules";
import { HeldSeatData } from "@zagrajmy/core/enrollment/schemas";
import type {
  Offer,
  PromotionState,
  WaitingParticipant,
} from "@zagrajmy/core/enrollment/schemas";
import { allowanceWindows } from "@zagrajmy/core/enrollment/windows";
import {
  DateTime,
  Duration,
  Effect,
  Layer,
  Option,
  Predicate,
  Schema,
} from "effect";
import { SqlClient } from "effect/sql/SqlClient";

import { asEnrollmentFailure } from "./enrollment-errors.js";
import { WINDOW_COLUMNS, WindowRow } from "./enrollment-store.js";
import {
  decodeFirst,
  decodeInput,
  decodeRows,
  IdRow,
  SqlDateTime,
  SqlDuration,
  toSqlDateTime,
} from "./rows.js";
import {
  lockSeatHoldersStatement,
  lockSessionRowStatement,
} from "./seat-locks.js";
import { seatsQuery } from "./seats.js";
import { SeatsRow } from "./shared-rows.js";
import { ROW_BUDGET } from "./sql-fragments.js";

const DEFAULT_OFFER_WINDOW = Duration.hours(24);

const WINDOW_BUDGET = 200;

const HeadRow = Schema.Struct({
  eventId: Schema.Int,
  eventSlug: Schema.String,
  offerClaimWindow: Schema.NullOr(SqlDuration),
  presenterId: Schema.NullOr(Schema.Int),
  promotionMode: Schema.NullOr(PromotionMode),
  sessionId: Schema.Int,
  sessionTitle: Schema.String,
  startTime: Schema.NullOr(SqlDateTime),
});

const WaitingRow = Schema.Struct({
  creationTime: SqlDateTime,
  email: Schema.String,
  name: Schema.String,
  participationId: Schema.Int,
  partyId: Schema.NullOr(Schema.Int),
  sponsorEmail: Schema.NullOr(Schema.String),
  sponsorId: Schema.NullOr(Schema.Int),
  userId: Schema.Int,
});

const AllowanceRow = Schema.Struct({ key: Schema.String, slots: Schema.Int });

const CompanionRow = Schema.Struct({
  companionId: Schema.Int,
  managerId: Schema.Int,
});

const UserIdRow = Schema.Struct({ id: Schema.Int });

const WindowLengthRow = Schema.Struct({
  offerClaimWindow: Schema.NullOr(SqlDuration),
});

const OfferRow = Schema.Struct({
  creationTime: SqlDateTime,
  eventSlug: Schema.String,
  offerExpiresAt: Schema.NullOr(SqlDateTime),
  participationId: Schema.Int,
  recipientUserId: Schema.Int,
  sessionId: Schema.Int,
  sessionTitle: Schema.String,
});

const IdentityRow = Schema.Struct({
  claimToken: Schema.String,
  sessionId: Schema.Int,
});

const Ids = Schema.Array(Schema.Int);

const TokenInput = Schema.Struct({
  sphereId: Schema.Int,
  token: Schema.String,
});

const MemberInput = Schema.Struct({
  sessionId: Schema.Int,
  userId: Schema.Int,
});

const LapsedInput = Schema.Struct({
  now: Schema.DateTimeUtc,
  sphereId: Schema.Int,
});

const ClaimInput = Schema.Struct({
  claimedAt: Schema.DateTimeUtc,
  participationIds: Ids,
});

const Writes = Schema.Array(PromotionWrite);

const OfferConflictInput = Schema.Struct({
  participationIds: Ids,
  sessionId: Schema.Int,
});

const sumBy = (
  rows: readonly { readonly key: string; readonly slots: number }[]
) => {
  const totals = new Map<string, number>();

  for (const row of rows) {
    totals.set(row.key, (totals.get(row.key) ?? 0) + row.slots);
  }

  return totals;
};

const domainOf = (email: string) =>
  email.includes("@") ? (email.split("@")[1] ?? "") : "";

export const makePromotionStore = Effect.gen(function* makePromotionStore() {
  const sql = yield* SqlClient;

  const lockAndReadState = Effect.fn("PromotionStore.lockAndReadState")(
    function* lockAndReadState(sessionId: number) {
      const operation = "PromotionStore.lockAndReadState";
      const id = yield* decodeInput(operation, Schema.Int)(sessionId);
      const now = yield* DateTime.now;

      yield* lockSessionRowStatement(sql, id).pipe(
        decodeRows(operation, IdRow)
      );

      const head = yield* sql`
      SELECT s.id AS sessionId, s.title AS sessionTitle, s.presenter_id AS presenterId,
        s.event_id AS eventId, e.slug AS eventSlug, a.start_time AS startTime,
        c.promotion_mode AS promotionMode, c.offer_claim_window AS offerClaimWindow
      FROM session s JOIN event e ON e.id = s.event_id
      LEFT JOIN agenda_item a ON a.session_id = s.id
      LEFT JOIN proposal_category c ON c.id = s.category_id
      WHERE s.id = ${id} AND s.deleted_at IS NULL
    `.pipe(decodeFirst(operation, HeadRow));

      if (Option.isNone(head) || head.value.startTime === null) {
        yield* Effect.logInfo(
          "session is gone or unscheduled; nobody is promoted"
        ).pipe(Effect.annotateLogs({ sessionId: id }));

        return Option.none<PromotionState>();
      }

      const session = head.value;
      const { startTime } = head.value;

      const seats = yield* seatsQuery({
        limit: 1,
        now: toSqlDateTime(now),
        sql,
        where: sql`s.id = ${id}`,
      }).pipe(decodeFirst(operation, SeatsRow));

      const waitingRows = yield* sql`
      SELECT p.id AS participationId, p.user_id AS userId, p.party_id AS partyId,
        p.creation_time AS creationTime, u.name AS name, u.email AS email,
        sponsor.id AS sponsorId, sponsor.email AS sponsorEmail
      FROM session_participant p
      JOIN user u ON u.id = p.user_id
      LEFT JOIN user sponsor ON sponsor.id = u.manager_id AND u.user_type = 'connected'
      WHERE p.session_id = ${id} AND p.status = 'waiting'
      ORDER BY p.creation_time, p.id LIMIT ${ROW_BUDGET.participationsPerSession}
    `.pipe(decodeRows(operation, WaitingRow));

      const waitingIds = waitingRows.map((row) => row.userId);

      if (waitingIds.length > 0) {
        yield* lockSeatHoldersStatement(sql, waitingIds).pipe(
          decodeRows(operation, IdRow)
        );
      }

      const conflicted =
        waitingIds.length === 0
          ? []
          : yield* sql`
      SELECT DISTINCT p.user_id AS id
      FROM agenda_item me
      JOIN session mine ON mine.id = me.session_id
      JOIN session other ON other.event_id = mine.event_id AND other.id <> mine.id AND other.deleted_at IS NULL
      JOIN agenda_item oa ON oa.session_id = other.id
      JOIN session_participant p ON p.session_id = other.id AND p.status IN ('confirmed', 'offered')
      WHERE me.session_id = ${id} AND ${sql.in("p.user_id", waitingIds)}
        AND oa.start_time < me.end_time AND oa.end_time > me.start_time
      LIMIT ${waitingIds.length}
    `.pipe(decodeRows(operation, UserIdRow));

      const recipients = new Map(
        waitingRows.map((row) => [
          row.userId,
          {
            email:
              row.sponsorId === null ? row.email : (row.sponsorEmail ?? ""),
            id: row.sponsorId ?? row.userId,
          },
        ])
      );

      const owners = [
        ...new Map(
          [...recipients.values()].map((owner) => [owner.id, owner])
        ).values(),
      ];

      const emails = [
        ...new Set(
          owners.flatMap((owner) => (owner.email === "" ? [] : [owner.email]))
        ),
      ];

      const domains = [
        ...new Set(
          emails.flatMap((email) => {
            const domain = domainOf(email);

            return domain === "" ? [] : [domain];
          })
        ),
      ];

      const windows =
        yield* sql`SELECT ${sql.literal(WINDOW_COLUMNS)} FROM enrollment_config ec
        WHERE ec.event_id = ${session.eventId} ORDER BY ec.id LIMIT ${WINDOW_BUDGET}`.pipe(
          decodeRows(operation, WindowRow)
        );

      const configIds = allowanceWindows({ now, windows }).map(
        (window) => window.pk
      );

      const userAllowed =
        configIds.length === 0 || emails.length === 0
          ? new Map<string, number>()
          : sumBy(
              yield* sql`SELECT user_email AS key, allowed_slots AS slots FROM user_enrollment_config
                WHERE ${sql.in("enrollment_config_id", configIds)} AND ${sql.in("user_email", emails)}
                LIMIT ${ROW_BUDGET.participationsPerSession}`.pipe(
                decodeRows(operation, AllowanceRow)
              )
            );

      const domainAllowed =
        configIds.length === 0 || domains.length === 0
          ? new Map<string, number>()
          : sumBy(
              yield* sql`SELECT domain AS key, allowed_slots_per_user AS slots FROM domain_enrollment_config
                WHERE ${sql.in("enrollment_config_id", configIds)} AND ${sql.in("domain", domains)}
                LIMIT ${ROW_BUDGET.participationsPerSession}`.pipe(
                decodeRows(operation, AllowanceRow)
              )
            );

      const configured = owners.filter(
        (owner) =>
          userAllowed.has(owner.email) ||
          domainAllowed.has(domainOf(owner.email))
      );

      const ownerIds = configured.map((owner) => owner.id);

      const companions =
        ownerIds.length === 0
          ? []
          : yield* sql`SELECT id AS companionId, manager_id AS managerId FROM user
              WHERE user_type = 'connected' AND ${sql.in("manager_id", ownerIds)}
              LIMIT ${ROW_BUDGET.participationsPerSession}`.pipe(
              decodeRows(operation, CompanionRow)
            );

      const households = new Map(
        ownerIds.map((ownerId) => [
          ownerId,
          [
            ownerId,
            ...companions
              .filter((row) => row.managerId === ownerId)
              .map((row) => row.companionId),
          ],
        ])
      );

      const householdIds = [...households.values()].flat();

      const occupying =
        householdIds.length === 0
          ? []
          : (yield* sql`SELECT DISTINCT p.user_id AS id FROM session_participant p
              JOIN session s ON s.id = p.session_id
              WHERE s.event_id = ${session.eventId} AND p.status IN ('confirmed', 'offered')
                AND ${sql.in("p.user_id", householdIds)}
              LIMIT ${householdIds.length}`.pipe(
              decodeRows(operation, UserIdRow)
            )).map((row) => row.id);

      const slotsByOwner = new Map(
        owners.map((owner) => [
          owner.id,
          ownerSlotsRemaining({
            domainAllowed,
            occupyingHouseholdUserIds: occupying.filter((userId) =>
              (households.get(owner.id) ?? []).includes(userId)
            ),
            ownerEmail: owner.email,
            userAllowed,
          }),
        ])
      );

      const shadowbanned =
        session.presenterId === null
          ? []
          : yield* sql`SELECT target_id AS id FROM shadowban WHERE owner_id = ${session.presenterId}
              ORDER BY target_id LIMIT ${ROW_BUDGET.bans}`.pipe(
              decodeRows(operation, UserIdRow)
            );

      const conflictedIds = new Set(conflicted.map((row) => row.id));

      const waiting = waitingRows.map((row): WaitingParticipant => {
        const recipient = recipients.get(row.userId) ?? {
          email: row.email,
          id: row.userId,
        };

        return {
          creationTime: row.creationTime,
          email: row.email,
          fullName: row.name,
          hasConflict: conflictedIds.has(row.userId),
          ownerSlotsRemaining: slotsByOwner.get(recipient.id) ?? 0,
          participationId: row.participationId,
          partyId: row.partyId,
          recipientUserId: recipient.id,
          sponsorId: row.sponsorId,
          userId: row.userId,
        };
      });

      const state: PromotionState = {
        availableSeats: Option.match(seats, {
          onNone: () => 0,
          onSome: (found) => found.seatsLeft,
        }),
        eventSlug: session.eventSlug,
        offerClaimWindow: session.offerClaimWindow ?? DEFAULT_OFFER_WINDOW,
        presenterId: session.presenterId,
        promotionMode: session.promotionMode ?? "auto",
        sessionId: session.sessionId,
        sessionTitle: session.sessionTitle,
        shadowbannedUserIds: shadowbanned.map((row) => row.id),
        startTime,
        waiting,
      };

      return Option.some(state);
    }
  );

  const apply = Effect.fn("PromotionStore.apply")(function* apply(
    writes: readonly PromotionWrite[]
  ) {
    const operation = "PromotionStore.apply";
    const valid = yield* decodeInput(operation, Writes)(writes);
    const now = toSqlDateTime(yield* DateTime.now);

    for (const write of valid) {
      if (write.participationIds.length === 0) {
        continue;
      }

      yield* Predicate.isTagged(write, "Confirm")
        ? sql`UPDATE session_participant SET status = 'confirmed', modification_time = ${now}
            WHERE ${sql.in("id", write.participationIds)} RETURNING id`.pipe(
            decodeRows(operation, IdRow)
          )
        : sql`UPDATE session_participant SET ${sql.update({
            claim_token: write.claimToken,
            modification_time: now,
            offer_expires_at: toSqlDateTime(write.offerExpiresAt),
            offered_at: toSqlDateTime(write.offeredAt),
            status: "offered",
          })} WHERE ${sql.in("id", write.participationIds)} RETURNING id`.pipe(
            decodeRows(operation, IdRow)
          );
    }
  });

  const createOffered = Effect.fn("PromotionStore.createOffered")(
    function* createOffered(seat: typeof HeldSeatData.Type) {
      const operation = "PromotionStore.createOffered";
      const input = yield* decodeInput(operation, HeldSeatData)(seat);
      const now = toSqlDateTime(yield* DateTime.now);

      const rows = yield* sql`INSERT INTO session_participant ${sql.insert({
        claim_token: input.claimToken,
        claimed_at: null,
        creation_time: now,
        enrolled_by_id: null,
        modification_time: now,
        offer_expires_at: toSqlDateTime(input.offerExpiresAt),
        offered_at: toSqlDateTime(input.offeredAt),
        party_id: input.partyId,
        session_id: input.sessionId,
        status: "offered",
        user_id: input.userId,
      })} RETURNING id`.pipe(decodeRows(operation, IdRow));

      return rows[0]?.id ?? 0;
    }
  );

  const readOfferClaimWindow = Effect.fn("PromotionStore.readOfferClaimWindow")(
    function* readOfferClaimWindow(sessionId: number) {
      const operation = "PromotionStore.readOfferClaimWindow";
      const id = yield* decodeInput(operation, Schema.Int)(sessionId);

      const row =
        yield* sql`SELECT c.offer_claim_window AS offerClaimWindow FROM session s
        LEFT JOIN proposal_category c ON c.id = s.category_id WHERE s.id = ${id}`.pipe(
          decodeFirst(operation, WindowLengthRow)
        );

      return Option.match(row, {
        onNone: () => DEFAULT_OFFER_WINDOW,
        onSome: (found) => found.offerClaimWindow ?? DEFAULT_OFFER_WINDOW,
      });
    }
  );

  const party = (operation: string, identity: typeof IdentityRow.Type) =>
    Effect.gen(function* readParty() {
      const now = yield* DateTime.now;

      const rows = yield* sql`
      SELECT p.id AS participationId, p.session_id AS sessionId, p.creation_time AS creationTime,
        p.offer_expires_at AS offerExpiresAt, s.title AS sessionTitle, e.slug AS eventSlug,
        CASE WHEN u.user_type = 'connected' AND u.manager_id IS NOT NULL THEN u.manager_id ELSE u.id END AS recipientUserId
      FROM session_participant p
      JOIN user u ON u.id = p.user_id
      JOIN session s ON s.id = p.session_id
      JOIN event e ON e.id = s.event_id
      WHERE p.session_id = ${identity.sessionId} AND p.claim_token = ${identity.claimToken}
        AND p.status = 'offered'
      ORDER BY p.creation_time, p.id LIMIT ${ROW_BUDGET.participationsPerSession}
    `.pipe(decodeRows(operation, OfferRow));

      const [lead] = rows;

      if (lead === undefined) {
        return Option.none<Offer>();
      }

      const offer: Offer = {
        eventSlug: lead.eventSlug,
        offerExpiresAt: lead.offerExpiresAt ?? now,
        participantIds: rows.map((row) => row.participationId),
        recipients: distinctRecipients(rows.map((row) => row.recipientUserId)),
        sessionId: lead.sessionId,
        sessionTitle: lead.sessionTitle,
      };

      return Option.some(offer);
    });

  const partyOf = (
    operation: string,
    identity: Option.Option<typeof IdentityRow.Type>
  ) =>
    Option.match(identity, {
      onNone: () => Effect.succeed(Option.none<Offer>()),
      onSome: (found) => party(operation, found),
    });

  const readOfferByToken = Effect.fn("PromotionStore.readOfferByToken")(
    function* readOfferByToken(query: typeof TokenInput.Type) {
      const operation = "PromotionStore.readOfferByToken";
      const input = yield* decodeInput(operation, TokenInput)(query);

      if (input.token === "") {
        return Option.none<Offer>();
      }

      const identity = yield* sql`
      SELECT p.session_id AS sessionId, p.claim_token AS claimToken FROM session_participant p
      JOIN session s ON s.id = p.session_id JOIN event e ON e.id = s.event_id
      WHERE p.claim_token = ${input.token} AND p.status = 'offered' AND e.sphere_id = ${input.sphereId}
      ORDER BY p.id LIMIT 1
    `.pipe(decodeFirst(operation, IdentityRow));

      return yield* partyOf(operation, identity);
    }
  );

  const readOfferByParticipation = Effect.fn(
    "PromotionStore.readOfferByParticipation"
  )(function* readOfferByParticipation(participationId: number) {
    const operation = "PromotionStore.readOfferByParticipation";
    const id = yield* decodeInput(operation, Schema.Int)(participationId);

    const identity = yield* sql`
      SELECT session_id AS sessionId, claim_token AS claimToken FROM session_participant
      WHERE id = ${id} AND status = 'offered' AND claim_token <> ''
    `.pipe(decodeFirst(operation, IdentityRow));

    return yield* partyOf(operation, identity);
  });

  const readOfferForMember = Effect.fn("PromotionStore.readOfferForMember")(
    function* readOfferForMember(seat: typeof MemberInput.Type) {
      const operation = "PromotionStore.readOfferForMember";
      const input = yield* decodeInput(operation, MemberInput)(seat);

      const identity = yield* sql`
      SELECT session_id AS sessionId, claim_token AS claimToken FROM session_participant
      WHERE user_id = ${input.userId} AND session_id = ${input.sessionId}
        AND status = 'offered' AND claim_token <> '' ORDER BY id LIMIT 1
    `.pipe(decodeFirst(operation, IdentityRow));

      return yield* partyOf(operation, identity);
    }
  );

  const listLapsedOffers = Effect.fn("PromotionStore.listLapsedOffers")(
    function* listLapsedOffers(query: typeof LapsedInput.Type) {
      const operation = "PromotionStore.listLapsedOffers";
      const input = yield* decodeInput(operation, LapsedInput)(query);

      const rows = yield* sql`
      SELECT MIN(p.id) AS id FROM session_participant p
      JOIN session s ON s.id = p.session_id JOIN event e ON e.id = s.event_id
      WHERE p.status = 'offered' AND p.offer_expires_at < ${toSqlDateTime(input.now)}
        AND e.sphere_id = ${input.sphereId}
      GROUP BY p.claim_token ORDER BY p.claim_token LIMIT ${ROW_BUDGET.lapsedOffers}
    `.pipe(decodeRows(operation, UserIdRow));

      return rows.map((row) => row.id);
    }
  );

  const markClaimed = Effect.fn("PromotionStore.markClaimed")(
    function* markClaimed(claim: typeof ClaimInput.Type) {
      const operation = "PromotionStore.markClaimed";
      const input = yield* decodeInput(operation, ClaimInput)(claim);

      if (input.participationIds.length === 0) {
        return 0;
      }

      const now = toSqlDateTime(yield* DateTime.now);

      const rows = yield* sql`
      UPDATE session_participant SET status = 'confirmed', claimed_at = ${toSqlDateTime(input.claimedAt)},
        modification_time = ${now}
      WHERE ${sql.in("id", input.participationIds)} AND status = 'offered' RETURNING id
    `.pipe(decodeRows(operation, IdRow));

      return rows.length;
    }
  );

  const drop = Effect.fn("PromotionStore.drop")(function* drop(
    participationIds: readonly number[]
  ) {
    const operation = "PromotionStore.drop";
    const ids = yield* decodeInput(operation, Ids)(participationIds);

    if (ids.length === 0) {
      return 0;
    }

    const rows = yield* sql`
      DELETE FROM session_participant WHERE ${sql.in("id", ids)} AND status = 'offered' RETURNING id
    `.pipe(decodeRows(operation, IdRow));

    return rows.length;
  });

  const lockSessionRow = Effect.fn("PromotionStore.lockSessionRow")(
    function* lockSessionRow(sessionId: number) {
      const operation = "PromotionStore.lockSessionRow";
      const id = yield* decodeInput(operation, Schema.Int)(sessionId);

      const rows = yield* lockSessionRowStatement(sql, id).pipe(
        decodeRows(operation, IdRow)
      );

      return rows.length > 0;
    }
  );

  const holdersOf = (operation: string, participationIds: readonly number[]) =>
    sql`SELECT user_id AS id FROM session_participant WHERE ${sql.in("id", participationIds)}
      LIMIT ${participationIds.length}`.pipe(decodeRows(operation, UserIdRow));

  const lockOfferHolders = Effect.fn("PromotionStore.lockOfferHolders")(
    function* lockOfferHolders(participationIds: readonly number[]) {
      const operation = "PromotionStore.lockOfferHolders";
      const ids = yield* decodeInput(operation, Ids)(participationIds);

      if (ids.length === 0) {
        return;
      }

      const holders = (yield* holdersOf(operation, ids)).map((row) => row.id);

      if (holders.length > 0) {
        yield* lockSeatHoldersStatement(sql, holders).pipe(
          decodeRows(operation, IdRow)
        );
      }
    }
  );

  const conflictedOfferIds = Effect.fn("PromotionStore.conflictedOfferIds")(
    function* conflictedOfferIds(query: typeof OfferConflictInput.Type) {
      const operation = "PromotionStore.conflictedOfferIds";
      const input = yield* decodeInput(operation, OfferConflictInput)(query);

      if (input.participationIds.length === 0) {
        return [];
      }

      const rows = yield* sql`
      SELECT DISTINCT mine.id AS id
      FROM session_participant mine
      JOIN agenda_item me ON me.session_id = mine.session_id
      JOIN session_participant p ON p.user_id = mine.user_id AND p.session_id <> mine.session_id
        AND p.status IN ('confirmed', 'offered')
      JOIN session other ON other.id = p.session_id AND other.deleted_at IS NULL
      JOIN session here ON here.id = mine.session_id AND here.event_id = other.event_id
      JOIN agenda_item oa ON oa.session_id = other.id
      WHERE mine.session_id = ${input.sessionId} AND ${sql.in("mine.id", input.participationIds)}
        AND oa.start_time < me.end_time AND oa.end_time > me.start_time
      ORDER BY mine.id LIMIT ${input.participationIds.length}
    `.pipe(decodeRows(operation, UserIdRow));

      return rows.map((row) => row.id);
    }
  );

  const fail = asEnrollmentFailure;

  return PromotionStore.of({
    apply: (writes) => apply(writes).pipe(fail("PromotionStore.apply")),
    conflictedOfferIds: (query) =>
      conflictedOfferIds(query).pipe(fail("PromotionStore.conflictedOfferIds")),
    createOffered: (seat) =>
      createOffered(seat).pipe(fail("PromotionStore.createOffered")),
    drop: (ids) => drop(ids).pipe(fail("PromotionStore.drop")),
    listLapsedOffers: (query) =>
      listLapsedOffers(query).pipe(fail("PromotionStore.listLapsedOffers")),
    lockAndReadState: (sessionId) =>
      lockAndReadState(sessionId).pipe(fail("PromotionStore.lockAndReadState")),
    lockOfferHolders: (ids) =>
      lockOfferHolders(ids).pipe(fail("PromotionStore.lockOfferHolders")),
    lockSessionRow: (sessionId) =>
      lockSessionRow(sessionId).pipe(fail("PromotionStore.lockSessionRow")),
    markClaimed: (claim) =>
      markClaimed(claim).pipe(fail("PromotionStore.markClaimed")),
    readOfferByParticipation: (id) =>
      readOfferByParticipation(id).pipe(
        fail("PromotionStore.readOfferByParticipation")
      ),
    readOfferByToken: (query) =>
      readOfferByToken(query).pipe(fail("PromotionStore.readOfferByToken")),
    readOfferClaimWindow: (sessionId) =>
      readOfferClaimWindow(sessionId).pipe(
        fail("PromotionStore.readOfferClaimWindow")
      ),
    readOfferForMember: (seat) =>
      readOfferForMember(seat).pipe(fail("PromotionStore.readOfferForMember")),
  });
});

export const PromotionStoreLive = Layer.effect(
  PromotionStore,
  makePromotionStore
);
