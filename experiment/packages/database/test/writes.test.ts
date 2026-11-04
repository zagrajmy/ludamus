import { expect, layer } from "@effect/vitest";
import {
  ChangeLogStore,
  EventId,
  FacilitatorStore,
  ParticipationStore,
  PartyStore,
  SessionId,
  SpaceId,
  StoreTransaction,
  TrackStore,
  UserId,
} from "@zagrajmy/core";
import { DateTime, Effect, Option, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";
import { TestClock } from "effect/testing";

import { DatabaseTest } from "../src/database-test.js";
import { brand, countRows } from "./seed.js";

const eventId = brand(EventId);

const userId = brand(UserId);

const kapitularz = eventId(28);

const worstCase = eventId(42);

const fixedNow = DateTime.makeUnsafe("2026-11-02T08:00:00Z");

const storedChanges = Effect.gen(function* storedChanges() {
  const sql = yield* SqlClient;

  const rows =
    yield* sql`SELECT changes FROM facilitator_change_log ORDER BY id DESC LIMIT 1`.pipe(
      Effect.flatMap(
        Schema.decodeUnknownEffect(
          Schema.Array(Schema.Struct({ changes: Schema.String }))
        )
      )
    );

  return rows[0]?.changes;
});

layer(DatabaseTest, { buildPerTest: true })("store writes", (it) => {
  it.effect(
    "tracks: create, rename and reassign within the event; names are unique case-insensitively",
    () =>
      Effect.gen(function* step1() {
        yield* TestClock.setTime(DateTime.toEpochMillis(fixedNow));
        const tracks = yield* TrackStore;

        const created = yield* tracks.create({
          eventId: worstCase,
          track: {
            isPublic: false,
            managerIds: [userId(1)],
            name: "Night Games",
            slug: "night-games",
            spaceIds: [],
          },
        });

        const duplicate = yield* Effect.flip(
          tracks.create({
            eventId: worstCase,
            track: {
              isPublic: true,
              managerIds: [],
              name: "night GAMES",
              slug: "night-games-2",
              spaceIds: [],
            },
          })
        );

        const foreignSpace = brand(SpaceId)(1);

        const updated = yield* tracks.update({
          eventId: worstCase,
          id: created.id,
          track: {
            isPublic: true,
            managerIds: [],
            name: "Late Games",
            slug: "late-games",
            spaceIds: [foreignSpace],
          },
        });

        const wrongEvent = yield* Effect.flip(
          tracks.delete({ eventId: kapitularz, id: created.id })
        );

        expect(created).toMatchObject({
          isPublic: false,
          name: "Night Games",
          slug: "night-games",
        });
        expect(DateTime.formatIso(created.creationTime)).toBe(
          "2026-11-02T08:00:00.000Z"
        );
        expect(duplicate._tag).toBe("DuplicateName");
        expect(updated).toMatchObject({
          isPublic: true,
          name: "Late Games",
          slug: "late-games",
        });
        expect(yield* tracks.spaceIds(created.id)).toEqual([]);
        expect(yield* tracks.managerIds(created.id)).toEqual([]);
        expect(wrongEvent._tag).toBe("NotFound");
        yield* tracks.delete({ eventId: worstCase, id: created.id });
        expect(
          Option.isNone(
            yield* tracks.findByName({ eventId: worstCase, name: "late games" })
          )
        ).toBe(true);
      })
  );

  it.effect(
    "facilitators: a soft-deleted row leaves the list but keeps its slug reserved",
    () =>
      Effect.gen(function* step2() {
        yield* TestClock.setTime(DateTime.toEpochMillis(fixedNow));
        const facilitators = yield* FacilitatorStore;

        const host = yield* facilitators.readBySlug({
          eventId: kapitularz,
          slug: "host-001",
        });

        yield* facilitators.softDelete({ eventId: kapitularz, id: host.id });

        const alive = yield* facilitators.listByEvent({
          eventId: kapitularz,
          filters: {},
        });

        const bin = yield* facilitators.listDeletedByEvent(kapitularz);

        const reserved = yield* facilitators.slugExists({
          eventId: kapitularz,
          slug: "host-001",
        });

        const hidden = yield* Effect.flip(
          facilitators.readBySlug({ eventId: kapitularz, slug: "host-001" })
        );

        const counts = yield* facilitators.countSessions({
          eventId: kapitularz,
          id: host.id,
        });

        const foreignRestore = yield* Effect.flip(
          facilitators.restore({ eventId: worstCase, id: host.id })
        );

        yield* facilitators.restore({ eventId: kapitularz, id: host.id });

        expect(alive).toHaveLength(71);
        expect(bin.map((item) => item.displayName)).toEqual(["Host 001"]);
        expect(DateTime.formatIso(bin[0]?.deletedAt ?? fixedNow)).toBe(
          "2026-11-02T08:00:00.000Z"
        );
        expect(reserved).toBe(true);
        expect(hidden._tag).toBe("NotFound");
        expect(counts).toEqual({ deleted: 0, live: 1 });
        expect(foreignRestore._tag).toBe("NotFound");
        expect(
          yield* facilitators.listByEvent({ eventId: kapitularz, filters: {} })
        ).toHaveLength(72);
      })
  );

  it.effect(
    "facilitators: an accreditation change writes the change log Django writes",
    () =>
      Effect.gen(function* step3() {
        yield* TestClock.setTime(DateTime.toEpochMillis(fixedNow));
        const facilitators = yield* FacilitatorStore;
        const logs = yield* ChangeLogStore;

        const host = yield* facilitators.readBySlug({
          eventId: kapitularz,
          slug: "host-002",
        });

        yield* facilitators.update({
          changes: { accreditationType: "guest" },
          eventId: kapitularz,
          id: host.id,
        });
        yield* logs.logFacilitatorChange({
          changes: [
            {
              field: "accreditation_type",
              fieldId: null,
              new: "guest",
              old: host.accreditationType,
            },
          ],
          eventId: kapitularz,
          facilitatorId: host.id,
          userId: userId(1),
        });

        const listed = yield* logs.listFacilitatorChanges({
          before: null,
          key: kapitularz,
        });

        const older = yield* logs.listFacilitatorChanges({
          before: { creationTime: fixedNow, id: listed[0]?.id ?? 0 },
          key: kapitularz,
        });

        expect(
          (yield* facilitators.readInEvent({
            eventId: kapitularz,
            id: host.id,
          })).accreditationType
        ).toBe("guest");
        expect(yield* storedChanges).toBe(
          `[{"field": "accreditation_type", "field_id": null, "new": "guest", "old": "${host.accreditationType}"}]`
        );
        expect(
          listed.map((entry) => [
            entry.facilitatorName,
            entry.changes[0]?.fieldId,
            entry.changes[0]?.new,
          ])
        ).toEqual([["Host 002", null, "guest"]]);
        expect(older).toEqual([]);
      })
  );

  it.effect(
    "a failed capability rolls back every write inside StoreTransaction.atomic",
    () =>
      Effect.gen(function* step4() {
        const transaction = yield* StoreTransaction;
        const participations = yield* ParticipationStore;
        const before = yield* countRows("session_participant");

        const outcome = yield* Effect.flip(
          transaction.atomic(
            Effect.gen(function* outcome() {
              yield* participations.upsertSeat({
                partyId: null,
                sessionId: brand(SessionId)(11),
                status: "confirmed",
                userId: userId(1),
              });

              return yield* Effect.fail("abandoned");
            })
          )
        );

        expect(outcome).toBe("abandoned");
        expect(yield* countRows("session_participant")).toBe(before);
      })
  );

  it.effect(
    "offers: an offered seat holds capacity, a claim confirms it, a lapse drops it",
    () =>
      Effect.gen(function* step5() {
        yield* TestClock.setTime(DateTime.toEpochMillis(fixedNow));
        const participations = yield* ParticipationStore;
        const session = brand(SessionId)(11);
        const offeredAt = fixedNow;
        const offerExpiresAt = DateTime.add(fixedNow, { hours: 24 });

        const held = yield* participations.createOffered({
          claimToken: "token-a",
          offerExpiresAt,
          offeredAt,
          partyId: null,
          sessionId: session,
          userId: userId(1),
        });

        const [seats] = yield* participations.seats({
          now: fixedNow,
          sessionIds: [session],
        });

        const party = yield* participations.findOfferByToken("token-a");
        const lapsedEarly = yield* participations.listLapsedOffers(fixedNow);

        const lapsedLate = yield* participations.listLapsedOffers(
          DateTime.add(fixedNow, { hours: 25 })
        );

        const claimed = yield* participations.markClaimed({
          claimedAt: fixedNow,
          ids: [held.id],
        });

        const droppedAfterClaim = yield* participations.dropOffered([held.id]);

        expect(seats?.enrolledCount).toBe(1);
        expect(
          party.pipe(
            Option.map((found) => [found.eventSlug, found.members.length])
          )
        ).toEqual(Option.some(["enroll-states", 1]));
        expect(lapsedEarly).not.toContain(held.id);
        expect(lapsedLate).toContain(held.id);
        expect(claimed).toBe(1);
        expect(droppedAfterClaim).toBe(0);
      })
  );

  it.effect(
    "parties: the leader joins as an active member; deleting releases seats",
    () =>
      Effect.gen(function* step6() {
        yield* TestClock.setTime(DateTime.toEpochMillis(fixedNow));
        const parties = yield* PartyStore;
        const participations = yield* ParticipationStore;
        const leader = userId(1);

        const partyId = yield* parties.create({
          inviteToken: "invite-a",
          leaderId: leader,
          name: "Crew",
        });

        const joined = yield* parties.joinViaToken({
          token: "invite-a",
          userId: userId(2),
        });

        const rejoined = yield* parties.joinViaToken({
          token: "invite-a",
          userId: userId(2),
        });

        const seat = yield* participations.upsertSeat({
          partyId,
          sessionId: brand(SessionId)(11),
          status: "confirmed",
          userId: leader,
        });

        const listed = yield* parties.readForViewer({
          partyId,
          viewerId: userId(2),
        });

        const strangerDelete = yield* parties.delete({
          leaderId: userId(2),
          partyId,
        });

        const deleted = yield* parties.delete({ leaderId: leader, partyId });
        const kept = yield* participations.listForSession(brand(SessionId)(11));

        expect(joined.pipe(Option.map((join) => join.joined))).toEqual(
          Option.some(true)
        );
        expect(rejoined.pipe(Option.map((join) => join.joined))).toEqual(
          Option.some(false)
        );
        expect(
          listed.pipe(
            Option.map((party) =>
              party.members.map((member) => [
                member.user.id,
                member.status,
                member.consentMode,
              ])
            )
          )
        ).toEqual(
          Option.some([
            [1, "active", "accept_by_default"],
            [2, "active", "accept_invites"],
          ])
        );
        expect(strangerDelete).toBe(false);
        expect(deleted).toBe(true);
        expect(kept.find((row) => row.id === seat.id)?.partyId).toBeNull();
      })
  );
});
