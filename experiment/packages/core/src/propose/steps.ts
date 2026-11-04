import { Effect, Result } from "effect";

import { TimeSlotId, TrackId } from "../ids.js";
import { NotFound } from "../ports/store-error.js";
import { unfoldCustomAnswers } from "../proposal/fields.js";
import { fieldError, lastPosted } from "../proposal/form-fields.js";
import type { FieldError, FormData } from "../proposal/form-fields.js";
import {
  validateDetailsStep,
  validatePersonalStep,
} from "../proposal/wizard.js";
import { requireChosen, resolveCategory, stepsOf } from "./context.js";
import type { Wizard } from "./context.js";
import { ProposalInvalid } from "./proposal-invalid.js";
import {
  CategoryAccepted,
  DetailsAccepted,
  PersonalAccepted,
  TimeSlotsAccepted,
} from "./schemas.js";
import type {
  AcceptedStep,
  Answers,
  CheckableStep,
  DetailsAnswers,
  PersonalAnswers,
  ProposeWizardCategory,
} from "./schemas.js";

const DECIMAL_ID = /^[0-9]+$/u;

const invalid = (
  step: CheckableStep,
  errors: Readonly<Record<string, readonly FieldError[]>>
) => new ProposalInvalid({ errors, step });

export const personalFormValues = (options: {
  readonly wizard: Wizard;
  readonly personal: PersonalAnswers;
}): Answers => ({
  ...unfoldCustomAnswers({
    fields: options.wizard.personalFields.map((pair) => pair.field),
    prefix: "personal",
    stored: options.personal.answers,
  }),
  contact_email: options.personal.contactEmail,
});

export const checkPersonal = Effect.fn("Propose.checkPersonal")(
  function* checkPersonal(options: {
    readonly wizard: Wizard;
    readonly category: ProposeWizardCategory | null;
    readonly data: FormData | null;
  }) {
    const { wizard } = options;

    if (!stepsOf(options).includes("personal")) {
      const implied: PersonalAnswers = {
        answers: wizard.account.personalAnswers,
        contactEmail: wizard.account.email,
      };

      return implied;
    }

    const outcome = validatePersonalStep({
      data: options.data ?? {},
      fields: wizard.personalFields,
    });

    if (Result.isFailure(outcome)) {
      return yield* invalid("personal", outcome.failure);
    }

    const accepted: PersonalAnswers = outcome.success;

    return accepted;
  }
);

export const checkTimeSlots = Effect.fn("Propose.checkTimeSlots")(
  function* checkTimeSlots(options: {
    readonly wizard: Wizard;
    readonly category: ProposeWizardCategory | null;
    readonly posted: readonly string[];
  }) {
    const chosen = yield* requireChosen(options);
    const slots = chosen?.timeSlots ?? [];

    if (!stepsOf(options).includes("timeslots")) {
      return slots.length === 1 ? slots.map((slot) => slot.id) : [];
    }

    const valid = new Set(slots.map((slot) => String(slot.id)));
    const selected = options.posted.filter((id) => valid.has(id));

    if (selected.length === 0) {
      return yield* invalid("timeslots", {
        time_slot_ids: [
          fieldError("required", "Please select at least one time slot."),
        ],
      });
    }

    return selected.map((id) => TimeSlotId.make(Number(id)));
  }
);

export const checkDetails = Effect.fn("Propose.checkDetails")(
  function* checkDetails(options: {
    readonly wizard: Wizard;
    readonly category: ProposeWizardCategory | null;
    readonly data: FormData;
  }) {
    const chosen = yield* requireChosen(options);
    const requirements = chosen?.sessionFields ?? [];
    const { tracks } = options.wizard;
    const valid = new Set(tracks.map((track) => String(track.id)));

    const trackIds = (options.data.track_pks ?? [])
      .filter((id) => valid.has(id))
      .map((id) => TrackId.make(Number(id)));

    const outcome = validateDetailsStep({
      category: chosen,
      data: options.data,
      requirements,
    });

    const trackErrors =
      tracks.length > 0 && trackIds.length === 0
        ? {
            track_pks: [
              fieldError("required", "Please select at least one track."),
            ],
          }
        : {};

    if (Result.isFailure(outcome)) {
      return yield* invalid("details", { ...outcome.failure, ...trackErrors });
    }

    if (Object.keys(trackErrors).length > 0) {
      return yield* invalid("details", trackErrors);
    }

    const details: DetailsAnswers = outcome.success;

    return {
      details,
      formValues: unfoldCustomAnswers({
        fields: requirements.map((pair) => pair.field),
        prefix: "session",
        stored: details.answers,
      }),
      trackIds,
    };
  }
);

export const checkCategory = Effect.fn("Propose.checkCategory")(
  function* checkCategory(options: {
    readonly wizard: Wizard;
    readonly data: FormData;
  }) {
    const raw = lastPosted(options.data, "category_id");

    if (raw === "") {
      return yield* invalid("category", {
        category_id: [fieldError("required", "Please select a category.")],
      });
    }

    const picked = DECIMAL_ID.test(raw)
      ? options.wizard.categories.find(
          (category) => String(category.id) === raw
        )
      : undefined;

    if (picked === undefined) {
      return yield* new NotFound({ entity: "ProposalCategory", key: raw });
    }

    return picked;
  }
);

export const checkStep = Effect.fn("Propose.checkStep")(function* checkStep(
  options: Readonly<{
    wizard: Wizard;
    step: CheckableStep;
    categoryId: number | null;
    data: FormData;
  }>
) {
  const { data, wizard } = options;

  if (options.step === "category") {
    const picked = yield* checkCategory({ data, wizard });

    const accepted: AcceptedStep = CategoryAccepted.make({
      categoryId: picked.id,
    });

    return accepted;
  }

  const category = yield* resolveCategory({
    categoryId: options.categoryId,
    wizard,
  });

  if (options.step === "personal") {
    const personal = yield* checkPersonal({ category, data, wizard });

    const accepted: AcceptedStep = PersonalAccepted.make({
      formValues: personalFormValues({ personal, wizard }),
      personal,
    });

    return accepted;
  }

  if (options.step === "timeslots") {
    const timeSlotIds = yield* checkTimeSlots({
      category,
      posted: data.time_slot_ids ?? [],
      wizard,
    });

    const accepted: AcceptedStep = TimeSlotsAccepted.make({ timeSlotIds });

    return accepted;
  }

  const details = yield* checkDetails({ category, data, wizard });
  const accepted: AcceptedStep = DetailsAccepted.make(details);

  return accepted;
});
