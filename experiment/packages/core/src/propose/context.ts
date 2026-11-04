import { DateTime, Effect, Option } from "effect";

import { isOpen, isProposalActive } from "../event.js";
import type { PersonalDataField, SessionField } from "../fields.js";
import { CurrentSphere } from "../ports/current-sphere.js";
import { CurrentViewer } from "../ports/current-viewer.js";
import { EventStore } from "../ports/event-store.js";
import { FieldStore } from "../ports/field-store.js";
import { ProposalCategoryStore } from "../ports/proposal-category-store.js";
import { NotFound } from "../ports/store-error.js";
import { TrackStore } from "../ports/track-store.js";
import { UserDirectory } from "../ports/user-store.js";
import type { FieldRequirement, OrganizerField } from "../proposal/fields.js";
import {
  accountAnswersEverything,
  accountPersonalAnswers,
  pickCategory,
  wizardSteps,
} from "../proposal/wizard.js";
import type { ProposeStep } from "../proposal/wizard.js";
import { AnonymousProposalsDisabled } from "./anonymous-proposals-disabled.js";
import { CategoryRequired } from "./category-required.js";
import { ProposalsClosed } from "./proposals-closed.js";
import type {
  ProposeWizardCategory,
  ProposalTrack,
  ProposerAccount,
} from "./schemas.js";

export const sessionOrganizerField = (field: SessionField): OrganizerField => ({
  allowCustom: field.allowCustom,
  fieldType: field.fieldType,
  helpText: field.helpText,
  icon: field.icon,
  isMultiple: field.isMultiple,
  isPublic: field.isPublic,
  isRequired: false,
  maxLength: field.maxLength,
  name: field.name,
  options: field.options.map((option) => ({
    label: option.label,
    order: option.order,
    pk: option.id,
    value: option.value,
  })),
  order: field.order,
  pk: field.id,
  question: field.question,
  showOnCards: field.showOnCards,
  slug: field.slug,
});

export const personalOrganizerField = (
  field: PersonalDataField
): OrganizerField => ({
  allowCustom: field.allowCustom,
  fieldType: field.fieldType,
  helpText: field.helpText,
  icon: "",
  isMultiple: field.isMultiple,
  isPublic: field.isPublic,
  isRequired: field.isRequired,
  maxLength: field.maxLength,
  name: field.name,
  options: field.options.map((option) => ({
    label: option.label,
    order: option.order,
    pk: option.id,
    value: option.value,
  })),
  order: field.order,
  pk: field.id,
  question: field.question,
  showOnCards: false,
  slug: field.slug,
});

const NO_ACCOUNT: ProposerAccount = {
  answersEverything: false,
  email: "",
  name: "",
  personalAnswers: {},
  signedIn: false,
};

export const loadWizard = Effect.fn("Propose.loadWizard")(function* loadWizard(
  eventSlug: string
) {
  const sphere = yield* CurrentSphere;
  const viewer = yield* CurrentViewer;
  const events = yield* EventStore;
  const categoryStore = yield* ProposalCategoryStore;
  const fieldStore = yield* FieldStore;
  const trackStore = yield* TrackStore;
  const users = yield* UserDirectory;
  const now = yield* DateTime.now;

  const event = yield* events.readBySlug({
    slug: eventSlug,
    sphereId: sphere.id,
  });

  if (!isProposalActive(event, now)) {
    return yield* new ProposalsClosed({
      eventIsOpen: isOpen(event, now),
      eventSlug,
    });
  }

  const settings = yield* events.readProposalSettings(event.id);

  if (Option.isNone(viewer) && !settings.allowAnonymousProposals) {
    return yield* new AnonymousProposalsDisabled({ eventSlug });
  }

  const personalFields: readonly FieldRequirement[] =
    (yield* fieldStore.listPersonalDataFields(event.id)).map((field) => ({
      field: personalOrganizerField(field),
      isRequired: field.isRequired,
    }));

  const user = Option.isNone(viewer)
    ? Option.none()
    : Option.some(yield* users.readById(viewer.value.id));

  const account: ProposerAccount = Option.match(user, {
    onNone: () => NO_ACCOUNT,
    onSome: (found) => {
      const personalAnswers = accountPersonalAnswers({
        discordUsername: found.discordUsername,
        fields: personalFields.map((pair) => pair.field),
      });

      return {
        answersEverything: accountAnswersEverything({
          answers: personalAnswers,
          email: found.email,
          fields: personalFields,
        }),
        email: found.email,
        name: found.name,
        personalAnswers,
        signedIn: true,
      };
    },
  });

  const stored = yield* categoryStore.listByEvent(event.id);

  const categories: ProposeWizardCategory[] = [];

  for (const category of stored) {
    const requirements = yield* categoryStore.readRequirements(category.id);

    const timeSlots = requirements.timeSlots
      .map((requirement) => ({
        endTime: requirement.timeSlot.endTime,
        id: requirement.timeSlotId,
        isRequired: requirement.isRequired,
        startTime: requirement.timeSlot.startTime,
      }))
      .toSorted((a, b) => DateTime.Order(a.startTime, b.startTime));

    categories.push({
      description: category.description,
      durations: category.durations,
      id: category.id,
      maxParticipantsLimit: category.maxParticipantsLimit,
      minParticipantsLimit: category.minParticipantsLimit,
      name: category.name,
      sessionFields: requirements.sessionFields.map((requirement) => ({
        field: sessionOrganizerField(requirement.field),
        isRequired: requirement.isRequired,
      })),
      steps: [],
      timeSlots,
    });
  }

  const stepsFor = (category: ProposeWizardCategory | null) =>
    wizardSteps({
      accountAnswersEverything: account.answersEverything,
      categoryCount: categories.length,
      hasCategory: category !== null,
      timeSlotCount: category?.timeSlots.length ?? 0,
    });

  const tracks: readonly ProposalTrack[] = (yield* trackStore.listPublicByEvent(
    event.id
  )).map((track) => ({ id: track.id, name: track.name }));

  return {
    account,
    categories: categories.map((category) => ({
      ...category,
      steps: stepsFor(category),
    })),
    event,
    personalFields,
    settings,
    stepsFor,
    tracks,
    viewer,
  };
});

export type Wizard = Effect.Success<ReturnType<typeof loadWizard>>;

export const resolveCategory = Effect.fn("Propose.resolveCategory")(
  function* resolveCategory(options: {
    readonly wizard: Wizard;
    readonly categoryId: number | null;
  }) {
    const { categories } = options.wizard;

    if (options.categoryId === null) {
      return pickCategory({ categories, picked: null });
    }

    const picked = categories.find(
      (category) => category.id === options.categoryId
    );

    if (picked === undefined) {
      return yield* new NotFound({
        entity: "ProposalCategory",
        key: String(options.categoryId),
      });
    }

    return picked;
  }
);

export const requireChosen = Effect.fn("Propose.requireChosen")(
  function* requireChosen(options: {
    readonly wizard: Wizard;
    readonly category: ProposeWizardCategory | null;
  }) {
    if (options.category === null && options.wizard.categories.length > 0) {
      return yield* new CategoryRequired({
        eventSlug: options.wizard.event.slug,
      });
    }

    return options.category;
  }
);

export const stepsOf = (options: {
  readonly wizard: Wizard;
  readonly category: ProposeWizardCategory | null;
}): readonly ProposeStep[] =>
  options.category === null
    ? options.wizard.stepsFor(null)
    : options.category.steps;
