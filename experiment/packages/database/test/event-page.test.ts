import { describe, expect, layer } from "@effect/vitest";
import {
  CurrentSphere,
  SphereId,
  readEventPage,
  readEventSession,
} from "@zagrajmy/core";
import { DateTime, Effect } from "effect";
import { TestClock } from "effect/testing";

import { DatabaseTest } from "../src/database-test.js";
import { brand, seedNow } from "./seed.js";

const rootSphere = {
  domain: "localhost:8000",
  id: brand(SphereId)(1),
  name: "Root Domain Sphere",
};

const crewSphere = {
  domain: "crew.localhost:8000",
  id: brand(SphereId)(4),
  name: "Crew Sphere",
};

const atSeedTime = <A, E, R>(effect: Effect.Effect<A, E, R>) =>
  Effect.gen(function* pinClock() {
    const now = yield* seedNow;
    yield* TestClock.setTime(DateTime.toEpochMillis(now));

    return yield* effect;
  });

const pageOf = (slug: string, sphere = rootSphere) =>
  atSeedTime(
    readEventPage
      .handler({ slug })
      .pipe(Effect.provideService(CurrentSphere, sphere))
  );

layer(DatabaseTest)("readEventPage", (it) => {
  describe("which sessions an event page lists", () => {
    it.effect(
      "autumn-open lists its 3 public scheduled sessions as cards",
      () =>
        Effect.gen(function* autumnOpen() {
          const page = yield* pageOf("autumn-open");

          expect(page.isCompact).toBe(false);
          expect(page.sessions.map((card) => card.session.title)).toEqual([
            "Mega Strategy Lab",
            "Cozy Storytellers Circle",
            "Przygoda w Mieście Neonów",
          ]);
        })
    );

    it.effect(
      "kapitularz lists all 112 sessions and switches to the compact schedule",
      () =>
        Effect.gen(function* kapitularz() {
          const page = yield* pageOf("kapitularz-2025-anonymized");

          expect(page.sessions).toHaveLength(112);
          expect(page.isCompact).toBe(true);
        })
    );

    it.effect("a card names its room through the whole space tree", () =>
      Effect.gen(function* roomPath() {
        const page = yield* pageOf("autumn-open");

        const mega = page.sessions.find(
          (card) => card.session.title === "Mega Strategy Lab"
        );

        expect(mega?.location.path).toBe(
          "Convention Center > Main Hall > East Wing"
        );
        expect(mega?.location.sortPath.map((step) => step.name)).toEqual([
          "Convention Center",
          "Main Hall",
          "East Wing",
        ]);
      })
    );

    it.effect("offers only the public select fields as filters", () =>
      Effect.gen(function* filterFields() {
        const page = yield* pageOf("autumn-open");

        expect(
          page.filterFields.every(
            (field) => field.fieldType === "select" && field.isPublic
          )
        ).toBe(true);
        expect(page.filterFields.map((field) => field.slug)).toContain("mood");
      })
    );
  });

  describe("which events open", () => {
    it.effect("an unpublished unlisted event opens by its link", () =>
      Effect.gen(function* unlisted() {
        const page = yield* pageOf("crew-sneak-peek", crewSphere);

        expect(page.event.visibility).toBe("unlisted");
      })
    );

    it.effect(
      "another sphere's event is NotFound, not a leak across hosts",
      () =>
        Effect.gen(function* foreign() {
          const failure = yield* pageOf("autumn-open", crewSphere).pipe(
            Effect.flip
          );

          expect(failure._tag).toBe("NotFound");
        })
    );

    it.effect("an unknown slug is NotFound", () =>
      Effect.gen(function* unknown() {
        const failure = yield* pageOf("no-such-event").pipe(Effect.flip);

        expect(failure._tag).toBe("NotFound");
      })
    );
  });

  describe("readEventSession", () => {
    it.effect("reads one listed session with its roster", () =>
      Effect.gen(function* oneSession() {
        const page = yield* pageOf("autumn-open");

        const mega = page.sessions.find(
          (card) => card.session.title === "Mega Strategy Lab"
        );

        const card = yield* atSeedTime(
          readEventSession
            .handler({ sessionId: mega?.session.id ?? 0, slug: "autumn-open" })
            .pipe(Effect.provideService(CurrentSphere, rootSphere))
        );

        expect(card.session.title).toBe("Mega Strategy Lab");
      })
    );

    it.effect(
      "a session of another event is NotFound under this event's slug",
      () =>
        Effect.gen(function* foreignSession() {
          const page = yield* pageOf("kapitularz-2025-anonymized");
          const other = page.sessions[0]?.session.id ?? 0;

          const failure = yield* atSeedTime(
            readEventSession
              .handler({ sessionId: other, slug: "autumn-open" })
              .pipe(Effect.provideService(CurrentSphere, rootSphere))
          ).pipe(Effect.flip);

          expect(failure._tag).toBe("NotFound");
        })
    );
  });
});
