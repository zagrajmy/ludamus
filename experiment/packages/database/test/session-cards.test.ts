import { describe, expect, layer } from "@effect/vitest";
import {
  EventId,
  EventStore,
  SessionId,
  SessionStore,
  SphereId,
} from "@zagrajmy/core";
import { Effect, Option } from "effect";

import { DatabaseTest } from "../src/database-test.js";
import { brand, seedNow } from "./seed.js";

const rootSphere = brand(SphereId)(1);

const eventId = brand(EventId);

const sessionId = brand(SessionId);

const eventBySlug = (slug: string) =>
  Effect.gen(function* readEvent() {
    const events = yield* EventStore;

    return yield* events.readBySlug({ slug, sphereId: rootSphere });
  });

const cardsOf = (slug: string, rosterUpTo = 100) =>
  Effect.gen(function* readCards() {
    const sessions = yield* SessionStore;
    const event = yield* eventBySlug(slug);

    return yield* sessions.listScheduledCards({
      eventId: event.id,
      now: yield* seedNow,
      rosterUpTo,
    });
  });

layer(DatabaseTest)("SessionStore event page", (it) => {
  describe("visibility: only alive, scheduled sessions outside private tracks", () => {
    it.effect("autumn-open shows 3 of its 5 sessions, earliest first", () =>
      Effect.gen(function* step1() {
        const cards = yield* cardsOf("autumn-open");

        expect(cards.map((card) => card.session.title)).toEqual([
          "Mega Strategy Lab",
          "Cozy Storytellers Circle",
          "Przygoda w Mieście Neonów",
        ]);
      })
    );

    it.effect(
      "a session in a private track stays off the page even when scheduled",
      () =>
        Effect.gen(function* step2() {
          const sunhaven = yield* cardsOf("sunhaven-festival");
          const emberfall = yield* cardsOf("emberfall-con");

          expect(sunhaven.map((card) => card.session.title)).toEqual([
            "Overflow Demo Game",
          ]);
          expect(emberfall).toEqual([]);
        })
    );

    it.effect("the modal read refuses a session of another event", () =>
      Effect.gen(function* step3() {
        const sessions = yield* SessionStore;
        const now = yield* seedNow;

        const own = yield* sessions.readScheduledCard({
          eventId: eventId(11),
          now,
          sessionId: sessionId(17),
        });

        const foreign = yield* sessions.readScheduledCard({
          eventId: eventId(8),
          now,
          sessionId: sessionId(17),
        });

        expect(own.pipe(Option.map((card) => card.session.title))).toEqual(
          Option.some("Mega Strategy Lab")
        );
        expect(Option.isNone(foreign)).toBe(true);
      })
    );
  });

  describe("card shape matches scheduled_session_cards", () => {
    it.effect("names the room by its root-to-leaf path", () =>
      Effect.gen(function* step4() {
        const cards = yield* cardsOf("autumn-open");

        expect(cards[0]?.location.path).toBe(
          "Convention Center > Main Hall > East Wing"
        );
        expect(cards[0]?.location.parentName).toBe("Main Hall");
        expect(cards[0]?.location.sortPath.map((step) => step.name)).toEqual([
          "Convention Center",
          "Main Hall",
          "East Wing",
        ]);
        expect(cards[0]?.fieldValues).toHaveLength(2);
      })
    );

    it.effect(
      "carries track names and drops the roster at the roster threshold",
      () =>
        Effect.gen(function* step5() {
          const big = yield* cardsOf("kapitularz-2025-anonymized", 100);
          const withRoster = yield* cardsOf("kapitularz-2025-anonymized", 200);

          expect(big).toHaveLength(112);
          expect(big[0]?.trackNames).toEqual(["RPG"]);
          expect(big.every((card) => card.participations.length === 0)).toBe(
            true
          );
          expect(withRoster[0]?.participations).toHaveLength(6);
        })
    );
  });

  describe("seats follow Session.seats_left / is_full / effective_participants_limit", () => {
    it.effect("a full session in enroll-states has no seats left", () =>
      Effect.gen(function* step6() {
        const cards = yield* cardsOf("enroll-states");

        const seats = Object.fromEntries(
          cards.map((card) => [card.session.title, card.seats])
        );

        expect(seats["Waiting List Only Demo"]).toMatchObject({
          effectiveParticipantsLimit: 1,
          enrolledCount: 1,
          isFull: true,
          seatsLeft: 0,
        });
        expect(seats["Seat Available Demo"]).toMatchObject({
          isFull: false,
          seatsLeft: 5,
        });
        expect(cards[1]?.participations).toHaveLength(1);
      })
    );

    it.effect("a 50% window rounds the limit up, as math.ceil does", () =>
      Effect.gen(function* step7() {
        const cards = yield* cardsOf("early-access");

        expect(
          cards.map((card) => [
            card.seats.participantsLimit,
            card.seats.effectiveParticipantsLimit,
            card.seats.seatsLeft,
            card.seats.isFull,
          ])
        ).toEqual([
          [5, 3, 3, false],
          [5, 3, 2, false],
          [2, 1, 0, true],
        ]);
        expect(cards[0]?.seats.eligibleWindowIds).toEqual([4]);
      })
    );

    it.effect(
      "a session that takes no enrollment has no seats and is never full",
      () =>
        Effect.gen(function* step8() {
          const cards = yield* cardsOf("autumn-open");

          expect(cards[1]?.seats).toMatchObject({
            effectiveParticipantsLimit: 0,
            eligibleWindowIds: [],
            isFull: false,
            participantsLimit: 0,
          });
          expect(cards[0]?.seats).toMatchObject({
            effectiveParticipantsLimit: 24,
            eligibleWindowIds: [5],
          });
        })
    );

    it.effect("kapitularz keeps counting an over-booked session as full", () =>
      Effect.gen(function* step9() {
        const cards = yield* cardsOf("kapitularz-2025-anonymized");

        expect(cards[0]?.seats).toMatchObject({
          effectiveParticipantsLimit: 5,
          enrolledCount: 6,
          isFull: true,
          seatsLeft: 0,
        });
      })
    );
  });

  describe("review queue mirrors review_inbox_proposals", () => {
    it.effect("lists unscheduled pending proposals per event", () =>
      Effect.gen(function* step10() {
        const sessions = yield* SessionStore;
        const now = yield* seedNow;

        const counts = yield* Effect.forEach([11, 25, 41, 42, 8], (id) =>
          sessions
            .listProposalCards({ eventId: eventId(id), now, presenterId: null })
            .pipe(Effect.map((cards) => cards.length))
        );

        expect(counts).toEqual([2, 2, 1, 2, 0]);
      })
    );
  });
});
