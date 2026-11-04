import { describe, expect, layer } from "@effect/vitest";
import {
  BookmarkStore,
  EnrollmentConfigStore,
  EventId,
  FacilitatorStore,
  FieldStore,
  ParticipationStore,
  ProposalCategoryId,
  ProposalCategoryStore,
  SessionId,
  SphereId,
  TrackStore,
  UserDirectory,
  UserId,
} from "@zagrajmy/core";
import { Duration, Effect, Option } from "effect";

import { DatabaseTest } from "../src/database-test.js";
import { brand } from "./seed.js";

const eventId = brand(EventId);

const categoryId = brand(ProposalCategoryId);

const sessionId = brand(SessionId);

const userId = brand(UserId);

layer(DatabaseTest)("catalog reads", (it) => {
  describe("facilitators: alive only, Django's name ordering and live session counts", () => {
    it.effect("lists 72 kapitularz hosts and 11 worst-case facilitators", () =>
      Effect.gen(function* step1() {
        const facilitators = yield* FacilitatorStore;

        const kapitularz = yield* facilitators.listByEvent({
          eventId: eventId(28),
          filters: {},
        });

        const worstCase = yield* facilitators.listByEvent({
          eventId: eventId(42),
          filters: {},
        });

        expect(kapitularz).toHaveLength(72);
        expect(
          kapitularz
            .slice(0, 3)
            .map((item) => [item.displayName, item.sessionCount])
        ).toEqual([
          ["Host 001", 1],
          ["Host 002", 2],
          ["Host 003", 1],
        ]);
        expect(worstCase).toHaveLength(11);
      })
    );

    it.effect("honours the row limit a picker asks for", () =>
      Effect.gen(function* step2() {
        const facilitators = yield* FacilitatorStore;

        const page = yield* facilitators.listByEvent({
          eventId: eventId(28),
          filters: { limit: 5, sort: "-name" },
        });

        expect(page).toHaveLength(5);
        expect(page[0]?.displayName).toBe("Host 072");
      })
    );
  });

  describe("tracks", () => {
    it.effect("lists kapitularz tracks by name with their rooms", () =>
      Effect.gen(function* step3() {
        const tracks = yield* TrackStore;
        const all = yield* tracks.listByEvent(eventId(28));
        const assigned = yield* tracks.listWithAssignments(eventId(28));

        expect(all.map((track) => track.name)).toEqual([
          "Contests",
          "Cosplay",
          "Miniature Painting",
          "Publisher Tables",
          "RPG",
          "Workshops",
        ]);
        expect(assigned[0]).toMatchObject({
          managerNames: [],
          name: "Contests",
          spaceNames: [
            "Contest Stage",
            "Lecture Room 1",
            "Lecture Room 2",
            "Lecture Room 3",
          ],
        });
      })
    );

    it.effect("hides private tracks from the public list", () =>
      Effect.gen(function* step4() {
        const tracks = yield* TrackStore;
        const all = yield* tracks.listByEvent(eventId(37));
        const shown = yield* tracks.listPublicByEvent(eventId(37));

        expect(all.length - shown.length).toBe(2);
      })
    );
  });

  describe("proposal categories and fields", () => {
    it.effect(
      "lists autumn-open categories by name and their proposal counts",
      () =>
        Effect.gen(function* step5() {
          const categories = yield* ProposalCategoryStore;
          const listed = yield* categories.listByEvent(eventId(11));
          const stats = yield* categories.stats(eventId(42));

          expect(listed.map((category) => category.slug)).toEqual([
            "rpg-proposals",
            "roleplaying",
            "workshops",
          ]);
          expect(
            Duration.toHours(listed[0]?.offerClaimWindow ?? Duration.zero)
          ).toBe(24);
          expect(stats).toEqual([
            { acceptedCount: 1, categoryId: 16, proposalsCount: 3 },
            { acceptedCount: 1, categoryId: 17, proposalsCount: 1 },
          ]);
        })
    );

    it.effect(
      "reads a category's field and slot requirements in their order",
      () =>
        Effect.gen(function* step6() {
          const categories = yield* ProposalCategoryStore;
          const openMic = yield* categories.readRequirements(categoryId(8));
          const sunhaven = yield* categories.readRequirements(categoryId(12));

          expect(
            openMic.sessionFields.map((item) => [
              item.field.slug,
              item.isRequired,
              item.field.options.length,
            ])
          ).toEqual([
            ["tone", true, 2],
            ["triggers", false, 2],
            ["system", true, 0],
          ]);
          expect(sunhaven.timeSlots.map((item) => item.timeSlotId)).toEqual([
            37, 38,
          ]);
        })
    );

    it.effect("scopes a category to its event", () =>
      Effect.gen(function* step7() {
        const categories = yield* ProposalCategoryStore;

        const error = yield* Effect.flip(
          categories.readInEvent({ eventId: eventId(42), id: categoryId(8) })
        );

        expect(error._tag).toBe("NotFound");
      })
    );

    it.effect(
      "lists session fields in the organizer's order with their options",
      () =>
        Effect.gen(function* step8() {
          const fields = yield* FieldStore;
          const listed = yield* fields.listSessionFields(eventId(11));

          expect(
            listed.map((field) => [field.slug, field.options.length])
          ).toEqual([
            ["mood", 2],
            ["tone", 3],
            ["format", 1],
          ]);
        })
    );
  });

  describe("enrollment reads", () => {
    it.effect(
      "finds the user who has another confirmed seat at the same hour",
      () =>
        Effect.gen(function* step9() {
          const participations = yield* ParticipationStore;

          const conflicted = yield* participations.conflictedUserIds({
            sessionId: sessionId(3),
            userIds: [userId(1), userId(2), userId(3)],
          });

          const unscheduled = yield* participations.conflictedUserIds({
            sessionId: sessionId(12),
            userIds: [userId(1)],
          });

          expect(conflicted).toEqual([1]);
          expect(unscheduled).toEqual([]);
        })
    );

    it.effect("lists the enrollment windows of an event", () =>
      Effect.gen(function* step10() {
        const configs = yield* EnrollmentConfigStore;
        const windows = yield* configs.listByEvent(eventId(9));

        expect(
          windows.map((window) => [
            window.id,
            window.percentageSlots,
            window.limitToEndTime,
          ])
        ).toEqual([[4, 50, false]]);
      })
    );

    it.effect(
      "counts the one seeded bookmark and refuses a toggle from another sphere",
      () =>
        Effect.gen(function* step11() {
          const bookmarks = yield* BookmarkStore;
          const counts = yield* bookmarks.counts(eventId(33));

          const state = yield* bookmarks.sessionState({
            eventId: eventId(33),
            sessionId: sessionId(146),
            userId: userId(1),
          });

          const foreign = yield* bookmarks.toggle({
            sessionId: sessionId(146),
            sphereId: brand(SphereId)(1),
            userId: userId(1),
          });

          expect(counts).toEqual([{ count: 1, sessionId: 146 }]);
          expect(state).toEqual({ bookmarked: true, count: 1 });
          expect(Option.isNone(foreign)).toBe(true);
        })
    );

    it.effect("reads a user by id and the sponsor of nobody", () =>
      Effect.gen(function* step12() {
        const users = yield* UserDirectory;
        const user = yield* users.readById(userId(1));
        const sponsors = yield* users.sponsorsOf([userId(1)]);

        expect(user.id).toBe(1);
        expect(sponsors).toEqual([]);
      })
    );
  });
});
