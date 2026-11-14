import { implement } from "@zagrajmy/capability/implement";
import { Effect, Option } from "effect";

import { readProposalFormContract } from "../contracts.js";
import type { FieldValue } from "../fields.js";
import { CurrentSphere } from "../ports/current-sphere.js";
import { FacilitatorStore } from "../ports/facilitator-store.js";
import { FieldStore } from "../ports/field-store.js";
import { ProposerStore } from "../ports/proposer-store.js";
import { durationChoices } from "../proposal/durations.js";
import {
  resolveFieldControls,
  unfoldCustomAnswers,
} from "../proposal/fields.js";
import type { FieldAnswer, FieldRequirement } from "../proposal/fields.js";
import { REUSABLE_SESSIONS_LIMIT, carriedAnswers } from "../proposal/rules.js";
import { loadWizard } from "./context.js";
import type { Wizard } from "./context.js";
import type {
  Answers,
  ProposeWizard,
  ReusableSession,
  ReusableSessionRecord,
} from "./schemas.js";

const asAnswer = (value: FieldValue): FieldAnswer => value;

const detailsFieldNames = (options: {
  readonly durations: readonly string[];
  readonly requirements: readonly FieldRequirement[];
}): readonly string[] => [
  "title",
  "description",
  "participants_limit",
  "min_age",
  ...(durationChoices(options.durations).length > 0 ? ["duration"] : []),
  ...resolveFieldControls({
    pairs: options.requirements,
    prefix: "session",
  }).controls.map((control) => control.key),
];

export const reusableFormValues = (options: {
  readonly record: ReusableSessionRecord;
  readonly durations: readonly string[];
  readonly requirements: readonly FieldRequirement[];
}): Answers => {
  const { record } = options;

  const carried = carriedAnswers({
    presented: record.presented,
    private: record.privateAnswers,
    public: record.publicAnswers,
  });

  const copied = new Map<string, FieldAnswer>(
    Object.entries({
      ...unfoldCustomAnswers({
        fields: options.requirements.map((pair) => pair.field),
        prefix: "session",
        stored: Object.fromEntries(
          Object.entries(carried).map(([slug, value]) => [
            `session_${slug}`,
            asAnswer(value),
          ])
        ),
      }),
      description: record.description,
      duration: record.duration,
      min_age: String(record.minAge),
      participants_limit: record.participantsLimit
        ? String(record.participantsLimit)
        : "",
      title: record.title,
    })
  );

  return Object.fromEntries(
    detailsFieldNames(options).map((name) => [name, copied.get(name) ?? ""])
  );
};

const reusableSessions = Effect.fn("Propose.reusableSessions")(
  function* reusableSessions(wizard: Wizard) {
    if (Option.isNone(wizard.viewer)) {
      return [];
    }

    const sphere = yield* CurrentSphere;
    const proposers = yield* ProposerStore;

    const records = yield* proposers.listReusableSessions({
      excludeEventId: wizard.event.id,
      limit: REUSABLE_SESSIONS_LIMIT,
      sphereId: sphere.id,
      userId: wizard.viewer.value.id,
    });

    return records.map((record): ReusableSession => ({
      eventName: record.eventName,
      formValues: [
        {
          categoryId: null,
          values: reusableFormValues({
            durations: [],
            record,
            requirements: [],
          }),
        },
        ...wizard.categories.map((category) => ({
          categoryId: category.id,
          values: reusableFormValues({
            durations: category.durations,
            record,
            requirements: category.sessionFields,
          }),
        })),
      ],
      sessionId: record.sessionId,
      title: record.title,
    }));
  }
);

const savedPersonalAnswers = Effect.fn("Propose.savedPersonalAnswers")(
  function* savedPersonalAnswers(wizard: Wizard) {
    if (Option.isNone(wizard.viewer)) {
      return {};
    }

    const facilitators = yield* FacilitatorStore;
    const fields = yield* FieldStore;

    const facilitator = yield* facilitators.findByUser({
      eventId: wizard.event.id,
      userId: wizard.viewer.value.id,
    });

    if (Option.isNone(facilitator)) {
      return {};
    }

    const answers = yield* fields.readPersonalData({
      eventId: wizard.event.id,
      facilitatorId: facilitator.value.id,
    });

    return Object.fromEntries(
      answers.map((answer) => [`personal_${answer.fieldSlug}`, answer.value])
    );
  }
);

export const readProposalForm = implement(
  readProposalFormContract,
  ({ eventSlug }) =>
    Effect.gen(function* readProposalFormHandler() {
      const wizard = yield* loadWizard(eventSlug);
      const saved = yield* savedPersonalAnswers(wizard);

      const form: ProposeWizard = {
        account: wizard.account,
        categories: wizard.categories,
        event: {
          id: wizard.event.id,
          name: wizard.event.name,
          slug: wizard.event.slug,
        },
        personalFields: wizard.personalFields,
        personalFormValues: unfoldCustomAnswers({
          fields: wizard.personalFields.map((pair) => pair.field),
          prefix: "personal",
          stored: { ...saved, ...wizard.account.personalAnswers },
        }),
        proposalDescription: wizard.settings.description,
        reusableSessions: yield* reusableSessions(wizard),
        tracks: wizard.tracks,
        uncategorizedSteps: wizard.stepsFor(null),
      };

      return form;
    })
);
