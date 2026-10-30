import { describe, expect, layer } from "@effect/vitest";
import {
  EventId,
  FacilitatorId,
  ParticipationStore,
  SessionId,
  SessionStore,
  TrackId,
  UserId,
} from "@zagrajmy/core";
import type { NewSession } from "@zagrajmy/core";
import { DateTime, Effect, Exit, Option } from "effect";
import { TestClock } from "effect/testing";

import { DatabaseTest } from "../src/database-test.js";
import { brand, countRows, seedNow } from "./seed.js";

const eventId = brand(EventId);

const sessionId = brand(SessionId);

const autumnOpen = eventId(11);

const worstCase = eventId(42);

layer(DatabaseTest)("SessionStore panel reads", (it) => {
  describe("list_sessions_by_event", () => {
    it.effect(
      "scopes through the category, so a category-less session drops out",
      () =>
        Effect.gen(function* step1() {
          const sessions = yield* SessionStore;

          const all = yield* sessions.listByEvent({
            eventId: autumnOpen,
            filters: {},
          });

          const pending = yield* sessions.listByEvent({
            eventId: autumnOpen,
            filters: { status: "pending" },
          });

          const scheduled = yield* sessions.listByEvent({
            eventId: autumnOpen,
            filters: { scheduled: true },
          });

          expect([all.length, pending.length, scheduled.length]).toEqual([
            4, 4, 2,
          ]);
          expect(all[0]?.title).toBe("Open Table Proposal");
        })
    );

    it.effect("sorts by title with the newest pk breaking ties", () =>
      Effect.gen(function* step2() {
        const sessions = yield* SessionStore;

        const sorted = yield* sessions.listByEvent({
          eventId: autumnOpen,
          filters: { sort: { descending: false, key: "title" } },
        });

        expect(
          sorted.slice(0, 3).map((item) => item.title.slice(0, 15))
        ).toEqual(["Mega Strategy L", "Open Table Prop", "Pending Neon Pr"]);
      })
    );

    it.effect("search matches field answers stored as escaped JSON", () =>
      Effect.gen(function* step3() {
        const sessions = yield* SessionStore;

        const hits = yield* Effect.forEach(
          ["Cthulhu", "śledztwo", "Go"],
          (search) =>
            sessions
              .listByEvent({ eventId: worstCase, filters: { search } })
              .pipe(Effect.map((items) => items.length))
        );

        expect(hits).toEqual([1, 1, 1]);
      })
    );

    it.effect("counts sessions per track and status", () =>
      Effect.gen(function* step4() {
        const sessions = yield* SessionStore;

        expect(yield* sessions.countByTrack(worstCase)).toEqual([
          {
            accepted: 1,
            onHold: 0,
            pending: 0,
            rejected: 0,
            scheduled: 1,
            trackId: 15,
          },
        ]);
      })
    );

    it.effect("does not read a session through another event", () =>
      Effect.gen(function* step5() {
        const sessions = yield* SessionStore;

        const own = yield* sessions.readInEvent({
          eventId: autumnOpen,
          id: sessionId(17),
        });

        const foreign = yield* Effect.exit(
          sessions.readInEvent({ eventId: worstCase, id: sessionId(17) })
        );

        expect(own.title).toBe("Mega Strategy Lab");
        expect(Exit.isFailure(foreign) && foreign.cause.toString()).toContain(
          "NotFound"
        );
      })
    );
  });
});

const fixedNow = DateTime.makeUnsafe("2026-11-01T10:30:15.250Z");

const proposal = (overrides: Partial<NewSession>): NewSession => ({
  categoryId: null,
  contactEmail: "proposer@example.com",
  description: "",
  duration: "PT2H",
  eventId: autumnOpen,
  facilitatorIds: [],
  facilitatorName: "Proposer",
  ident: "",
  minAge: 0,
  participantsLimit: 6,
  presenterId: null,
  scheduleConfirmed: false,
  slug: "new-proposal",
  status: "pending",
  timeSlotIds: [],
  title: "New proposal",
  trackIds: [],
  ...overrides,
});

layer(DatabaseTest, { buildPerTest: true })("SessionStore writes", (it) => {
  it.effect(
    "a created session round-trips with Django's defaults and timestamps",
    () =>
      Effect.gen(function* step6() {
        yield* TestClock.setTime(DateTime.toEpochMillis(fixedNow));
        const sessions = yield* SessionStore;

        const id = yield* sessions.create(
          proposal({ presenterId: brand(UserId)(1) })
        );

        const stored = yield* sessions.read(id);

        expect(stored).toMatchObject({
          coverImage: "",
          deletedAt: null,
          ident: "",
          presenterId: 1,
          scheduleConfirmed: false,
          slug: "new-proposal",
          status: "pending",
        });
        expect(DateTime.formatIso(stored.creationTime)).toBe(
          "2026-11-01T10:30:15.250Z"
        );
        expect(DateTime.formatIso(stored.modificationTime)).toBe(
          "2026-11-01T10:30:15.250Z"
        );
        expect(
          yield* sessions.slugExists({
            eventId: autumnOpen,
            slug: "new-proposal",
          })
        ).toBe(true);
        expect(
          yield* sessions.slugExists({
            eventId: worstCase,
            slug: "new-proposal",
          })
        ).toBe(false);
      })
  );

  it.effect(
    "a foreign facilitator, slot or track aborts the create with no row written",
    () =>
      Effect.gen(function* step7() {
        const sessions = yield* SessionStore;
        const before = yield* countRows("session");

        const foreignFacilitator = yield* Effect.flip(
          sessions.create(
            proposal({ facilitatorIds: [brand(FacilitatorId)(999_999)] })
          )
        );

        const foreignTrack = yield* Effect.flip(
          sessions.create(proposal({ trackIds: [brand(TrackId)(15)] }))
        );

        expect(foreignFacilitator._tag).toBe("NotFound");
        expect(foreignTrack._tag).toBe("NotFound");
        expect(yield* countRows("session")).toBe(before);
      })
  );

  it.effect(
    "soft delete hides the session from every alive read; restore brings it back",
    () =>
      Effect.gen(function* step8() {
        const sessions = yield* SessionStore;
        const now = yield* seedNow;
        const scope = { eventId: autumnOpen, id: sessionId(17) };
        yield* sessions.softDelete(scope);

        const listed = yield* sessions.listByEvent({
          eventId: autumnOpen,
          filters: {},
        });

        const card = yield* sessions.readScheduledCard({
          eventId: autumnOpen,
          now,
          sessionId: sessionId(17),
        });

        const deleted = yield* sessions.listDeletedByEvent(autumnOpen);
        const again = yield* Effect.flip(sessions.softDelete(scope));

        const wrongEvent = yield* Effect.flip(
          sessions.restore({ eventId: worstCase, id: sessionId(17) })
        );

        yield* sessions.restore(scope);
        const restored = yield* sessions.read(sessionId(17));

        expect(listed.map((item) => item.id)).not.toContain(17);
        expect(Option.isNone(card)).toBe(true);
        expect(deleted.map((item) => [item.id, item.isDeleted])).toEqual([
          [17, true],
        ]);
        expect(again._tag).toBe("NotFound");
        expect(wrongEvent._tag).toBe("NotFound");
        expect(restored.deletedAt).toBeNull();
      })
  );

  it.effect("a status change through the wrong event changes nothing", () =>
    Effect.gen(function* step9() {
      const sessions = yield* SessionStore;

      const failure = yield* Effect.flip(
        sessions.update({
          changes: { status: "rejected" },
          eventId: worstCase,
          id: sessionId(17),
        })
      );

      yield* sessions.update({
        changes: { status: "rejected" },
        eventId: autumnOpen,
        id: sessionId(17),
      });

      expect(failure._tag).toBe("NotFound");
      expect((yield* sessions.read(sessionId(17))).status).toBe("rejected");
    })
  );

  it.effect(
    "upserting a seat counts it against the session and keeps its creation time",
    () =>
      Effect.gen(function* step10() {
        yield* TestClock.setTime(DateTime.toEpochMillis(fixedNow));
        const participations = yield* ParticipationStore;
        const now = yield* seedNow;

        const seat = {
          partyId: null,
          sessionId: sessionId(11),
          userId: brand(UserId)(1),
        };

        const created = yield* participations.upsertSeat({
          ...seat,
          status: "confirmed",
        });

        const [seats] = yield* participations.seats({
          now,
          sessionIds: [sessionId(11)],
        });

        yield* TestClock.adjust("1 hour");

        const moved = yield* participations.upsertSeat({
          ...seat,
          status: "waiting",
        });

        const removed = yield* participations.remove(seat);
        const removedAgain = yield* participations.remove(seat);

        expect(seats).toMatchObject({ enrolledCount: 1, seatsLeft: 4 });
        expect(moved.id).toBe(created.id);
        expect(moved.creationTime).toEqual(created.creationTime);
        expect(DateTime.formatIso(moved.modificationTime)).toBe(
          "2026-11-01T11:30:15.250Z"
        );
        expect(removed).toEqual(Option.some("waiting"));
        expect(Option.isNone(removedAgain)).toBe(true);
      })
  );
});
