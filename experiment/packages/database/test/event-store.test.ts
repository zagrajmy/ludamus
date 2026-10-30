import { describe, expect, layer } from "@effect/vitest";
import { EventStore, SphereId } from "@zagrajmy/core";
import { Effect, Exit, Schema } from "effect";

import { DatabaseTest } from "../src/database-test.js";
import { brand, seedNow } from "./seed.js";

const rootSphere = brand(SphereId)(1);

const crewSphere = brand(SphereId)(4);

const LooseSphereId = Schema.Number.pipe(Schema.brand("SphereId"));

layer(DatabaseTest)("EventStore", (it) => {
  describe("feed visibility hides what Django's listed_events hides", () => {
    it.effect("lists the 34 public, published events of the root sphere", () =>
      Effect.gen(function* step1() {
        const events = yield* EventStore;

        const feed = yield* events.listForFeed({
          includeHidden: false,
          now: yield* seedNow,
          sphereId: rootSphere,
        });

        expect(feed).toHaveLength(34);
        expect(feed.map((event) => event.slug)).not.toContain(
          "root-sneak-peek"
        );
      })
    );

    it.effect(
      "adds only the unlisted root-sneak-peek when hidden events are included",
      () =>
        Effect.gen(function* step2() {
          const events = yield* EventStore;
          const now = yield* seedNow;

          const listed = yield* events.listForFeed({
            includeHidden: false,
            now,
            sphereId: rootSphere,
          });

          const all = yield* events.listForFeed({
            includeHidden: true,
            now,
            sphereId: rootSphere,
          });

          const listedSlugs = new Set(listed.map((event) => event.slug));

          expect(all).toHaveLength(35);
          expect(
            all
              .filter((event) => !listedSlugs.has(event.slug))
              .map((event) => event.slug)
          ).toEqual(["root-sneak-peek"]);
        })
    );

    it.effect(
      "orders by start time, past-convention first and facilitator-edit-demo last",
      () =>
        Effect.gen(function* step3() {
          const events = yield* EventStore;

          const feed = yield* events.listForFeed({
            includeHidden: false,
            now: yield* seedNow,
            sphereId: rootSphere,
          });

          expect(feed[0]?.slug).toBe("past-convention");
          expect(feed.at(-1)?.slug).toBe("facilitator-edit-demo");
        })
    );

    it.effect("counts only public scheduled sessions per event", () =>
      Effect.gen(function* step4() {
        const events = yield* EventStore;

        const feed = yield* events.listForFeed({
          includeHidden: false,
          now: yield* seedNow,
          sphereId: rootSphere,
        });

        const counts = Object.fromEntries(
          feed.map((event) => [event.slug, event.sessionCount])
        );

        expect(counts["autumn-open"]).toBe(3);
        expect(counts["worst-case"]).toBe(7);
        expect(counts["kapitularz-2025-anonymized"]).toBe(112);
        expect(counts["past-convention"]).toBe(2);
      })
    );
  });

  describe("scoping", () => {
    it.effect("does not find another sphere's event by slug", () =>
      Effect.gen(function* step5() {
        const events = yield* EventStore;

        const foreign = yield* Effect.exit(
          events.readBySlug({ slug: "crew-open-night", sphereId: rootSphere })
        );

        const own = yield* events.readBySlug({
          slug: "crew-open-night",
          sphereId: crewSphere,
        });

        expect(Exit.isFailure(foreign) && foreign.cause.toString()).toContain(
          "NotFound"
        );
        expect(own.sphereId).toBe(crewSphere);
      })
    );

    it.effect("rejects a non-integer sphere id before querying", () =>
      Effect.gen(function* step6() {
        const events = yield* EventStore;

        const error = yield* Effect.flip(
          events.listBySphere(Schema.decodeSync(LooseSphereId)(1.5))
        );

        expect(error._tag).toBe("InvalidStoreInput");
      })
    );
  });
});
