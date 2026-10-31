import { expect, layer } from "@effect/vitest";
import { CurrentSphere, CurrentViewer, SphereId, UserId } from "@zagrajmy/core";
import type { Viewer } from "@zagrajmy/core";
import {
  deleteFacilitatorHandler,
  updateFacilitatorHandler,
} from "@zagrajmy/core/panel/facilitators";
import { changeProposalStatusHandler } from "@zagrajmy/core/panel/proposals";
import {
  FormInvalid,
  PanelAccessDenied,
  formError,
} from "@zagrajmy/core/panel/schemas";
import {
  createTrackHandler,
  deleteTrackHandler,
  updateTrackHandler,
} from "@zagrajmy/core/panel/tracks";
import { Effect, Option, Predicate, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";

import { DatabaseTest } from "../src/database-test.js";
import { brand, countRows } from "./seed.js";

const sphereId = brand(SphereId);

const userId = brand(UserId);

const root = {
  domain: "localhost:8000",
  id: sphereId(1),
  name: "Root Domain Sphere",
};

const crew = {
  domain: "crew.localhost:8000",
  id: sphereId(4),
  name: "Crew Sphere",
};

const manager: Viewer = { id: userId(15), isSuperuser: false };

const asViewer =
  (options: Readonly<{ sphere: typeof root; viewer: Option.Option<Viewer> }>) =>
  <A, E, R>(effect: Effect.Effect<A, E, R>) =>
    effect.pipe(
      Effect.provideService(CurrentSphere, options.sphere),
      Effect.provideService(CurrentViewer, options.viewer)
    );

const asRootManager = asViewer({ sphere: root, viewer: Option.some(manager) });

const trackForm = {
  eventSlug: "thornwood-days",
  isPublic: true,
  managerIds: [],
  name: "Lantern Stories",
  spaceIds: [36],
};

const scalar = (query: string) =>
  Effect.gen(function* readScalar() {
    const sql = yield* SqlClient;

    const rows = yield* sql
      .unsafe(query)
      .pipe(
        Effect.flatMap(
          Schema.decodeUnknownEffect(
            Schema.Array(Schema.Struct({ value: Schema.Unknown }))
          )
        )
      );

    return rows[0]?.value;
  });

layer(DatabaseTest, { buildPerTest: true })(
  "panel capabilities scope every id",
  (it) => {
    it.effect(
      "a track write naming an event of another sphere is NotFound and writes nothing",
      () =>
        Effect.gen(function* foreignEvent() {
          const before = yield* countRows("track");

          const failure = yield* createTrackHandler({
            ...trackForm,
            eventSlug: "crew-open-night",
          }).pipe(asRootManager, Effect.flip);

          expect(failure._tag).toBe("NotFound");
          expect(yield* countRows("track")).toBe(before);
        })
    );

    it.effect("a manager of one sphere is refused the panel of another", () =>
      Effect.gen(function* otherSphere() {
        const failure = yield* createTrackHandler({
          ...trackForm,
          eventSlug: "crew-open-night",
        }).pipe(
          asViewer({ sphere: crew, viewer: Option.some(manager) }),
          Effect.flip
        );

        expect(failure).toEqual(new PanelAccessDenied({ reason: "no_panel_access" }));
      })
    );

    it.effect(
      "a signed-out caller is asked to sign in before anything is read",
      () =>
        Effect.gen(function* signedOut() {
          const failure = yield* createTrackHandler(trackForm).pipe(
            asViewer({ sphere: root, viewer: Option.none() }),
            Effect.flip
          );

          expect(failure).toEqual(new PanelAccessDenied({ reason: "sign_in" }));
        })
    );

    it.effect("a comms member reads the panel but cannot write it", () =>
      Effect.gen(function* readOnlyRole() {
        const sql = yield* SqlClient;

        yield* sql`INSERT INTO sphere_managers (sphere_id, user_id, role) VALUES (1, 1, 'comms')`;
        const before = yield* countRows("track");

        const failure = yield* createTrackHandler(trackForm).pipe(
          asViewer({
            sphere: root,
            viewer: Option.some({ id: userId(1), isSuperuser: false }),
          }),
          Effect.flip
        );

        expect(failure).toEqual(new PanelAccessDenied({ reason: "read_only" }));
        expect(yield* countRows("track")).toBe(before);
      })
    );

    it.effect(
      "a space of another event in the body is refused and no track is created",
      () =>
        Effect.gen(function* foreignSpace() {
          const foreignSpaceId = yield* scalar(
            "SELECT id AS value FROM space WHERE event_id <> 15 LIMIT 1"
          );

          const before = yield* countRows("track");

          const failure = yield* createTrackHandler({
            ...trackForm,
            spaceIds: [Number(foreignSpaceId)],
          }).pipe(asRootManager, Effect.flip);

          expect(failure).toEqual(
        new FormInvalid({ errors: [formError("", "Choose spaces from this event and managers from this sphere.")] })
      );
          expect(yield* countRows("track")).toBe(before);
        })
    );

    it.effect(
      "a track of another event cannot be edited or deleted through this one",
      () =>
        Effect.gen(function* foreignTrack() {
          const update = yield* updateTrackHandler({
            ...trackForm,
            name: "Hijacked",
            trackSlug: "adventure",
          }).pipe(asRootManager, Effect.flip);

          const removal = yield* deleteTrackHandler({
            eventSlug: "thornwood-days",
            trackSlug: "adventure",
          }).pipe(asRootManager, Effect.flip);

          expect(update._tag).toBe("NotFound");
          expect(removal._tag).toBe("NotFound");
          expect(
            yield* scalar(
              "SELECT name AS value FROM track WHERE slug = 'adventure'"
            )
          ).toBe("Adventure");
        })
    );

    it.effect(
      "the same track name in another case is a duplicate, reported on the name field",
      () =>
        Effect.gen(function* duplicateName() {
          yield* createTrackHandler(trackForm).pipe(asRootManager);

          const failure = yield* createTrackHandler({
            ...trackForm,
            name: "LANTERN STORIES",
          }).pipe(asRootManager, Effect.flip);

          expect(failure).toEqual(
        new FormInvalid({ errors: [formError("name", "A track with this name already exists in this event. Pick another name.")] })
      );
        })
    );

    it.effect(
      "a proposal of another event is NotFound and keeps its status",
      () =>
        Effect.gen(function* foreignProposal() {
          const failure = yield* changeProposalStatusHandler({
            eventSlug: "autumn-open",
            proposalId: 150,
            status: "rejected",
          }).pipe(asRootManager, Effect.flip);

          expect(failure._tag).toBe("NotFound");
          expect(
            yield* scalar("SELECT status AS value FROM session WHERE id = 150")
          ).toBe("accepted");
        })
    );

    it.effect("a scheduled proposal can only stay accepted", () =>
      Effect.gen(function* scheduled() {
        const failure = yield* changeProposalStatusHandler({
          eventSlug: "sunhaven-festival",
          proposalId: 150,
          status: "rejected",
        }).pipe(asRootManager, Effect.flip);

        expect(failure._tag).toBe("ProposalScheduled");
        expect(
          yield* scalar("SELECT status AS value FROM session WHERE id = 150")
        ).toBe("accepted");
      })
    );

    it.effect(
      "a facilitator named on sessions is not deleted, and the refusal carries the counts",
      () =>
        Effect.gen(function* namedOnSessions() {
          const failure = yield* deleteFacilitatorHandler({
            eventSlug: "sunhaven-festival",
            facilitatorSlug: "alice-morgan",
          }).pipe(asRootManager, Effect.flip);

          expect(failure._tag).toBe("FacilitatorHasSessions");
          expect(
            yield* scalar(
              "SELECT deleted_at AS value FROM facilitator WHERE id = 82"
            )
          ).toBeNull();
        })
    );

    it.effect(
      "an accreditation outside the choices is a field error and the facilitator keeps its own",
      () =>
        Effect.gen(function* badAccreditation() {
          const before = yield* scalar(
            "SELECT accreditation_type AS value FROM facilitator WHERE id = 82"
          );

          const failure = yield* updateFacilitatorHandler({
            accreditationType: "vip",
            eventSlug: "sunhaven-festival",
            facilitatorSlug: "alice-morgan",
            internalComment: "",
            isCollective: false,
          }).pipe(asRootManager, Effect.flip);

          expect(
        Predicate.isTagged(failure, "FormInvalid")
          ? failure.errors.map((entry) => entry.field)
          : []
      ).toEqual(["accreditation_type"]);
          expect(
            yield* scalar(
              "SELECT accreditation_type AS value FROM facilitator WHERE id = 82"
            )
          ).toBe(before);
        })
    );
  }
);
