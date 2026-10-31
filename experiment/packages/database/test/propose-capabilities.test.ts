import { expect, layer } from "@effect/vitest";
import {
  ClientIp,
  CurrentSphere,
  CurrentViewer,
  SphereId,
  UserId,
} from "@zagrajmy/core";
import type { SubmitProposalInput } from "@zagrajmy/core/contracts";
import { checkProposalStep } from "@zagrajmy/core/propose/check-proposal-step";
import { readProposalForm } from "@zagrajmy/core/propose/read-proposal-form";
import { submitProposal } from "@zagrajmy/core/propose/submit-proposal";
import { DateTime, Effect, Option, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";
import { TestClock } from "effect/testing";

import { DatabaseTest } from "../src/database-test.js";
import { countRows, seedNow } from "./seed.js";

const OPEN_MIC_CATEGORY = 8;

const FROSTFIRE_CATEGORY = 4;

const TESTER = 1;

const REUSER = 32;

const atSeedTime = Effect.gen(function* atSeedTime() {
  yield* TestClock.setTime(DateTime.toEpochMillis(yield* seedNow));
});

const as =
  (options: Readonly<{ userId: number | null; ip: string | null }>) =>
  <A, E, R>(effect: Effect.Effect<A, E, R>) =>
    effect.pipe(
      Effect.provideService(
        CurrentViewer,
        options.userId === null
          ? Option.none()
          : Option.some({ id: UserId.make(options.userId), isSuperuser: false })
      ),
      Effect.provideService(ClientIp, Option.fromNullishOr(options.ip)),
      Effect.provideService(CurrentSphere, {
        domain: "localhost:8000",
        id: SphereId.make(1),
        name: "Root",
      })
    );

const anonymous = (ip: string | null) => as({ ip, userId: null });

const openMicProposal = (
  overrides: Partial<SubmitProposalInput> = {}
): SubmitProposalInput => ({
  categoryId: null,
  details: {
    description: ["A **drop-in** adventure."],
    duration: ["PT1H"],
    facilitator_name: ["Mystery GM"],
    min_age: ["0"],
    participants_limit: ["5"],
    session_system: ["Dungeon World"],
    session_tone: ["comedy"],
    session_triggers: ["horror"],
    session_triggers_custom: ["krew; przemoc"],
    title: ["Łódź Night: Śmiech"],
  },
  eventSlug: "open-mic",
  personal: {
    contact_email: ["anon@example.com"],
    "personal_first-time": ["true"],
  },
  timeSlotIds: [],
  ...overrides,
});

const SessionRow = Schema.Struct({
  categoryId: Schema.NullOr(Schema.Int),
  contactEmail: Schema.String,
  duration: Schema.String,
  facilitators: Schema.Int,
  presenterId: Schema.NullOr(Schema.Int),
  status: Schema.String,
});

const sessionRow = (sessionId: number) =>
  Effect.gen(function* readSessionRow() {
    const sql = yield* SqlClient;

    return yield* sql`
      SELECT s.category_id AS categoryId, s.contact_email AS contactEmail,
             s.duration AS duration, s.presenter_id AS presenterId, s.status AS status,
             (SELECT COUNT(*) FROM session_facilitators sf WHERE sf.session_id = s.id) AS facilitators
      FROM session s WHERE s.id = ${sessionId}`.pipe(
      Effect.flatMap(Schema.decodeUnknownEffect(Schema.Array(SessionRow)))
    );
  });

const answers = (sessionId: number) =>
  Effect.gen(function* readAnswers() {
    const sql = yield* SqlClient;

    return yield* sql`
      SELECT f.slug AS slug, v.value AS value FROM session_field_value v
      JOIN session_field f ON f.id = v.field_id
      WHERE v.session_id = ${sessionId} ORDER BY f.slug`.pipe(
      Effect.flatMap(
        Schema.decodeUnknownEffect(
          Schema.Array(
            Schema.Struct({ slug: Schema.String, value: Schema.String })
          )
        )
      )
    );
  });

layer(DatabaseTest, { buildPerTest: true })("propose capabilities", (it) => {
  it.effect(
    "a valid anonymous proposal is created pending, transliterated into its slug, with the write-ins folded into its answers",
    () =>
      Effect.gen(function* createsSession() {
        yield* atSeedTime;

        const submitted = yield* submitProposal.handler(openMicProposal());

        expect(submitted.slug).toBe("lodz-night-smiech");
        expect(yield* sessionRow(submitted.sessionId)).toEqual([
          {
            categoryId: OPEN_MIC_CATEGORY,
            contactEmail: "anon@example.com",
            duration: "PT1H",
            facilitators: 1,
            presenterId: null,
            status: "pending",
          },
        ]);
        expect(yield* answers(submitted.sessionId)).toEqual([
          { slug: "system", value: '"Dungeon World"' },
          { slug: "tone", value: '["comedy"]' },
          { slug: "triggers", value: '["horror", "krew", "przemoc"]' },
        ]);
      }).pipe(anonymous("203.0.113.7"))
  );

  it.effect(
    "a second proposal with the same title gets a suffixed slug instead of colliding",
    () =>
      Effect.gen(function* suffixedSlug() {
        yield* atSeedTime;

        const first = yield* submitProposal.handler(openMicProposal());

        const second = yield* submitProposal
          .handler(openMicProposal())
          .pipe(anonymous("203.0.113.8"));

        expect(second.slug).toMatch(/^lodz-night-smiech-[A-Za-z0-9_-]{4}$/u);
        expect(second.slug).not.toBe(first.slug);
      }).pipe(anonymous("203.0.113.7"))
  );

  it.effect(
    "a category of another event is NotFound and writes no session",
    () =>
      Effect.gen(function* foreignCategory() {
        yield* atSeedTime;
        const before = yield* countRows("session");

        const refused = yield* submitProposal
          .handler(openMicProposal({ categoryId: FROSTFIRE_CATEGORY }))
          .pipe(Effect.flip);

        expect(refused._tag).toBe("NotFound");
        expect(yield* countRows("session")).toBe(before);
      }).pipe(anonymous("203.0.113.7"))
  );

  it.effect(
    "an anonymous IP is refused its second proposal to the event within the window, another IP is not",
    () =>
      Effect.gen(function* rateLimit() {
        yield* atSeedTime;

        yield* submitProposal.handler(openMicProposal());
        const before = yield* countRows("session");

        const refused = yield* submitProposal
          .handler(openMicProposal())
          .pipe(Effect.flip);

        expect(refused._tag).toBe("SubmissionThrottled");
        expect(yield* countRows("session")).toBe(before);

        yield* submitProposal
          .handler(openMicProposal())
          .pipe(anonymous("198.51.100.1"));
        expect(yield* countRows("session")).toBe(before + 1);
      }).pipe(anonymous("203.0.113.7"))
  );

  it.effect(
    "submitters without a CF-Connecting-IP share one bucket, as get_client_ip's empty answer does",
    () =>
      Effect.gen(function* sharedBucket() {
        yield* atSeedTime;

        yield* submitProposal.handler(openMicProposal());

        const refused = yield* submitProposal
          .handler(openMicProposal())
          .pipe(Effect.flip);

        expect(refused._tag).toBe("SubmissionThrottled");
      }).pipe(anonymous(null))
  );

  it.effect(
    "the window passes: the same IP may propose again after five minutes",
    () =>
      Effect.gen(function* windowPasses() {
        yield* atSeedTime;

        yield* submitProposal.handler(openMicProposal());
        yield* TestClock.adjust("301 seconds");
        const again = yield* submitProposal.handler(openMicProposal());

        expect(again.title).toBe("Łódź Night: Śmiech");
      }).pipe(anonymous("203.0.113.7"))
  );

  it.effect("a signed-in proposer is never rate limited", () =>
    Effect.gen(function* signedIn() {
      yield* atSeedTime;

      const input = openMicProposal({
        personal: { contact_email: ["e2e@test.local"] },
      });

      yield* submitProposal.handler(input);
      const again = yield* submitProposal.handler(input);

      expect(yield* sessionRow(again.sessionId)).toMatchObject([
        { contactEmail: "e2e@test.local", presenterId: TESTER },
      ]);
    }).pipe(as({ ip: "203.0.113.7", userId: TESTER }))
  );

  it.effect(
    "the session step refuses an overlong write-in with Django's message and accepts it within the cap",
    () =>
      Effect.gen(function* detailsStep() {
        yield* atSeedTime;
        const { details } = openMicProposal();

        const refused = yield* checkProposalStep
          .handler({
            categoryId: null,
            data: { ...details, session_triggers_custom: ["a".repeat(51)] },
            eventSlug: "open-mic",
            step: "details",
          })
          .pipe(Effect.flip);

        expect(refused._tag).toBe("ProposalInvalid");
        expect(refused).toMatchObject({
          errors: {
            session_triggers_custom: [
              { code: "max_length", vars: { limit_value: 50, show_value: 51 } },
            ],
          },
        });

        const accepted = yield* checkProposalStep.handler({
          categoryId: null,
          data: details,
          eventSlug: "open-mic",
          step: "details",
        });

        expect(accepted._tag).toBe("DetailsAccepted");
        expect(accepted).toMatchObject({
          formValues: {
            session_triggers: ["horror"],
            session_triggers_custom: "krew; przemoc",
          },
        });
      }).pipe(anonymous("203.0.113.7"))
  );

  it.effect(
    "a returning proposer is offered their earlier session with its answers mapped onto this form",
    () =>
      Effect.gen(function* reusable() {
        yield* atSeedTime;

        const form = yield* readProposalForm.handler({
          eventSlug: "mothership-nights-2",
        });

        const [earlier] = form.reusableSessions;
        const [category] = form.categories;

        expect(form.uncategorizedSteps).not.toContain("personal");
        expect(earlier?.title).toBe("First time at the table? Play Mothership");
        expect(
          earlier?.formValues.find((entry) => entry.categoryId === category?.id)
            ?.values
        ).toMatchObject({
          duration: "PT2H",
          participants_limit: "4",
          session_equipment: ["Projector"],
          session_equipment_custom: "extension cord",
          session_notes: "A table near a socket, please.",
          session_system: "Mothership 1e",
        });
      }).pipe(as({ ip: null, userId: REUSER }))
  );

  it.effect(
    "an event that takes signed-in proposals only refuses an anonymous visitor",
    () =>
      Effect.gen(function* anonymousRefused() {
        yield* atSeedTime;

        const refused = yield* readProposalForm
          .handler({ eventSlug: "pub-night" })
          .pipe(Effect.flip);

        expect(refused._tag).toBe("AnonymousProposalsDisabled");
      }).pipe(anonymous("203.0.113.7"))
  );
});
