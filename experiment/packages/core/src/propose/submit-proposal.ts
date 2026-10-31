import { implement } from "@zagrajmy/capability/implement";
import { Effect, Option, Predicate, Random } from "effect";

import { submitProposalContract } from "../contracts.js";
import { PersonalDataFieldId } from "../ids.js";
import { ClientIp } from "../ports/client-ip.js";
import { FacilitatorStore } from "../ports/facilitator-store.js";
import { FieldStore } from "../ports/field-store.js";
import { ProposerStore } from "../ports/proposer-store.js";
import { SessionStore } from "../ports/session-store.js";
import { StoreError } from "../ports/store-error.js";
import { SubmissionThrottle } from "../ports/submission-throttle.js";
import { StoreTransaction } from "../ports/transaction.js";
import { normalizeDuration } from "../proposal/durations.js";
import { isEmptyAnswer } from "../proposal/fields.js";
import type { FieldAnswer, OrganizerField } from "../proposal/fields.js";
import {
  PROPOSAL_RATE_LIMIT_SECONDS,
  discordAnswer,
  proposalRateLimitKey,
} from "../proposal/rules.js";
import { PROPOSAL_SLUG_ATTEMPTS, slugCandidates } from "../proposal/slugify.js";
import { loadWizard, requireChosen, resolveCategory } from "./context.js";
import type { Wizard } from "./context.js";
import type { DetailsAnswers, PersonalAnswers } from "./schemas.js";
import { checkDetails, checkPersonal, checkTimeSlots } from "./steps.js";
import { SubmissionThrottled } from "./submission-throttled.js";

const URL_SAFE =
  "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

const TOKEN_BYTES = 3;

const tokenUrlsafe = Effect.gen(function* tokenUrlsafe() {
  const bytes: number[] = [];

  for (let index = 0; index < TOKEN_BYTES; index += 1) {
    bytes.push(yield* Random.nextIntBetween(0, 256));
  }

  const [a = 0, b = 0, c = 0] = bytes;
  const bits = a * 65_536 + b * 256 + c;

  return [262_144, 4096, 64, 1]
    .map((place) => URL_SAFE[Math.floor(bits / place) % 64] ?? "")
    .join("");
});

const uniqueSlug = Effect.fn("Propose.uniqueSlug")(function* uniqueSlug(
  options: Readonly<{
    title: string;
    exists: (slug: string) => Effect.Effect<boolean, StoreError>;
  }>
) {
  const suffixes: string[] = [];

  for (let index = 1; index < PROPOSAL_SLUG_ATTEMPTS; index += 1) {
    suffixes.push(yield* tokenUrlsafe);
  }

  for (const candidate of slugCandidates({
    fallback: "",
    suffixes,
    title: options.title,
  })) {
    if (!(yield* options.exists(candidate))) {
      return candidate;
    }
  }

  return yield* new StoreError({
    operation: "Propose.uniqueSlug",
    reason: "SlugCollisionError",
  });
});

const answeredByPrefix = (
  answers: Readonly<Record<string, FieldAnswer>>,
  prefix: string
): readonly (readonly [string, FieldAnswer])[] =>
  Object.entries(answers).flatMap(([key, value]) => {
    if (!key.startsWith(`${prefix}_`)) {
      return [];
    }

    const slug = key.slice(prefix.length + 1);

    return slug.endsWith("_custom") || isEmptyAnswer(value)
      ? []
      : [[slug, value] as const];
  });

const throttleAnonymous = Effect.fn("Propose.throttleAnonymous")(
  function* throttleAnonymous(wizard: Wizard) {
    if (Option.isSome(wizard.viewer)) {
      return;
    }

    const throttle = yield* SubmissionThrottle;
    const ip = Option.getOrElse(yield* ClientIp, () => "");

    const free = yield* throttle.reserve({
      key: proposalRateLimitKey({ eventId: wizard.event.id, ip }),
      seconds: PROPOSAL_RATE_LIMIT_SECONDS,
    });

    if (!free) {
      yield* Effect.logInfo("Proposal refused by the per-IP rate limit", {
        eventId: wizard.event.id,
      });

      yield* new SubmissionThrottled({ eventSlug: wizard.event.slug });
    }
  }
);

const findOrCreateFacilitator = Effect.fn("Propose.findOrCreateFacilitator")(
  function* findOrCreateFacilitator(options: {
    readonly wizard: Wizard;
    readonly displayName: string;
  }) {
    const facilitators = yield* FacilitatorStore;
    const { event, viewer } = options.wizard;

    if (Option.isSome(viewer)) {
      const found = yield* facilitators.findByUser({
        eventId: event.id,
        userId: viewer.value.id,
      });

      if (Option.isSome(found)) {
        return found.value;
      }
    }

    const slug = yield* uniqueSlug({
      exists: (candidate) =>
        facilitators
          .slugExists({ eventId: event.id, slug: candidate })
          .pipe(
            Effect.catchTag("InvalidStoreInput", () => Effect.succeed(true))
          ),
      title: options.displayName,
    });

    return yield* facilitators.create({
      accreditationType: "none",
      displayName: options.displayName,
      eventId: event.id,
      ident: "",
      isCollective: false,
      organizerId: null,
      slug,
      userId: Option.match(viewer, {
        onNone: () => null,
        onSome: (found) => found.id,
      }),
    });
  }
);

const savePersonalAnswers = Effect.fn("Propose.savePersonalAnswers")(
  function* savePersonalAnswers(options: {
    readonly wizard: Wizard;
    readonly facilitatorId: Parameters<
      FieldStore["Service"]["savePersonalData"]
    >[0]["facilitatorId"];
    readonly personal: PersonalAnswers;
  }) {
    const fields = yield* FieldStore;
    const { wizard } = options;

    const bySlug = new Map(
      wizard.personalFields.map((pair) => [pair.field.slug, pair.field])
    );

    const answers = answeredByPrefix(
      options.personal.answers,
      "personal"
    ).flatMap(
      ([slug, value]): readonly {
        field: OrganizerField;
        value: FieldAnswer;
      }[] => {
        const field = bySlug.get(slug);

        return field === undefined ? [] : [{ field, value }];
      }
    );

    if (answers.length > 0) {
      yield* fields.savePersonalData({
        eventId: wizard.event.id,
        facilitatorId: options.facilitatorId,
        values: answers.map(({ field, value }) => ({
          fieldId: PersonalDataFieldId.make(field.pk),
          value,
        })),
      });
    }

    if (Option.isNone(wizard.viewer)) {
      return;
    }

    const handle = discordAnswer(
      answers.flatMap(({ field, value }) =>
        Predicate.isString(value) ? [{ field, value }] : []
      )
    );

    if (handle === "") {
      return;
    }

    const proposers = yield* ProposerStore;

    const filled = yield* proposers.fillDiscordUsername({
      handle,
      userId: wizard.viewer.value.id,
    });

    if (filled) {
      yield* Effect.logInfo("Proposal filled the proposer's Discord handle", {
        eventId: wizard.event.id,
        userId: wizard.viewer.value.id,
      });
    }
  }
);

const writeProposal = Effect.fn("Propose.writeProposal")(
  function* writeProposal(options: {
    readonly wizard: Wizard;
    readonly categoryId: Wizard["categories"][number]["id"] | null;
    readonly details: DetailsAnswers;
    readonly personal: PersonalAnswers;
    readonly timeSlotIds: Parameters<
      SessionStore["Service"]["create"]
    >[0]["timeSlotIds"];
    readonly trackIds: Parameters<
      SessionStore["Service"]["create"]
    >[0]["trackIds"];
  }) {
    const sessions = yield* SessionStore;
    const fields = yield* FieldStore;
    const { details, wizard } = options;
    const { event, viewer } = wizard;

    const facilitator = yield* findOrCreateFacilitator({
      displayName: details.facilitatorName,
      wizard,
    });

    const slug = yield* uniqueSlug({
      exists: (candidate) =>
        sessions
          .slugExists({ eventId: event.id, slug: candidate })
          .pipe(
            Effect.catchTag("InvalidStoreInput", () => Effect.succeed(true))
          ),
      title: details.title,
    });

    const sessionId = yield* sessions.create({
      categoryId: options.categoryId,
      contactEmail: options.personal.contactEmail,
      description: details.description,
      duration: normalizeDuration(details.duration),
      eventId: event.id,
      facilitatorIds: [facilitator.id],
      facilitatorName: details.facilitatorName,
      ident: "",
      minAge: details.minAge,
      participantsLimit: details.participantsLimit,
      presenterId: Option.match(viewer, {
        onNone: () => null,
        onSome: (found) => found.id,
      }),
      scheduleConfirmed: false,
      slug,
      status: "pending",
      timeSlotIds: options.timeSlotIds,
      title: details.title,
      trackIds: options.trackIds,
    });

    const sessionFields = new Map(
      (yield* fields.listSessionFields(event.id)).map((field) => [
        field.slug,
        field.id,
      ])
    );

    const values = answeredByPrefix(details.answers, "session").flatMap(
      ([fieldSlug, value]) => {
        const fieldId = sessionFields.get(fieldSlug);

        return fieldId === undefined ? [] : [{ fieldId, value }];
      }
    );

    if (values.length > 0) {
      yield* sessions.saveFieldValues({ sessionId, values });
    }

    yield* savePersonalAnswers({
      facilitatorId: facilitator.id,
      personal: options.personal,
      wizard,
    });

    return { sessionId, slug, title: details.title };
  }
);

export const submitProposal = implement(submitProposalContract, (input) =>
  Effect.gen(function* submitProposalHandler() {
    const wizard = yield* loadWizard(input.eventSlug);

    const category = yield* resolveCategory({
      categoryId: input.categoryId,
      wizard,
    });

    const chosen = yield* requireChosen({ category, wizard });

    const personal = yield* checkPersonal({
      category,
      data: input.personal,
      wizard,
    });

    const timeSlotIds = yield* checkTimeSlots({
      category,
      posted: input.timeSlotIds.map(String),
      wizard,
    });

    const { details, trackIds } = yield* checkDetails({
      category,
      data: input.details,
      wizard,
    });

    yield* throttleAnonymous(wizard);

    const transaction = yield* StoreTransaction;

    const submitted = yield* transaction.atomic(
      writeProposal({
        categoryId: chosen?.id ?? null,
        details,
        personal,
        timeSlotIds,
        trackIds,
        wizard,
      })
    );

    yield* Effect.logInfo("Proposal submitted", {
      anonymous: Option.isNone(wizard.viewer),
      eventId: wizard.event.id,
      sessionId: submitted.sessionId,
    });

    return submitted;
  })
);
