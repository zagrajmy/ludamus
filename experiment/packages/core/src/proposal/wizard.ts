import { Result, Schema } from "effect";

import { durationChoices } from "./durations.js";
import {
  foldCustomAnswers,
  isTruthyAnswer,
  resolveFieldControls,
  validateFieldAnswers,
} from "./fields.js";
import type {
  FieldAnswer,
  FieldControl,
  FieldRequirement,
  OrganizerField,
} from "./fields.js";
import {
  CUSTOM_ANSWER_REQUIRED_ERROR,
  NULL_CHARACTERS_ERROR,
  REQUIRED_ERROR,
  cleanChar,
  cleanChoice,
  cleanEmail,
  cleanInteger,
  fieldError,
  invalidChoiceError,
  lastPosted,
  maxLengthError,
} from "./form-fields.js";
import type { FieldError, FormData, FormErrors } from "./form-fields.js";
import { pyLength, pyStrip } from "./python-text.js";

export const ProposeStep = Schema.Literals([
  "personal",
  "category",
  "timeslots",
  "details",
  "review",
]);

export type ProposeStep = typeof ProposeStep.Type;

export const STEP_ORDER: readonly ProposeStep[] = [
  "personal",
  "category",
  "timeslots",
  "details",
  "review",
];

export const FACILITATOR_NAME_FIELD = "facilitator_name";

export const TITLE_MAX_LENGTH = 255;

export const MAX_STORED_PARTICIPANTS_LIMIT = 2_147_483_647;

export const MIN_AGE_MAX = 80;

export const wizardSteps = (options: {
  readonly categoryCount: number;
  readonly hasCategory: boolean;
  readonly timeSlotCount: number;
  readonly accountAnswersEverything: boolean;
}): readonly ProposeStep[] => {
  const showsTimeSlots =
    (!options.hasCategory && options.categoryCount > 0) ||
    options.timeSlotCount > 1;

  return STEP_ORDER.filter(
    (step) =>
      (step !== "category" || options.categoryCount > 1) &&
      (step !== "timeslots" || showsTimeSlots) &&
      (step !== "personal" || !options.accountAnswersEverything)
  );
};

export const stepAtOrBefore = (
  steps: readonly ProposeStep[],
  step: ProposeStep
): ProposeStep => {
  const shown = STEP_ORDER.slice(0, STEP_ORDER.indexOf(step) + 1).filter(
    (key) => steps.includes(key)
  );

  return shown.at(-1) ?? steps[0] ?? "review";
};

export const stepAfter = (
  steps: readonly ProposeStep[],
  step: ProposeStep
): ProposeStep =>
  STEP_ORDER.slice(STEP_ORDER.indexOf(step) + 1).find((key) =>
    steps.includes(key)
  ) ?? "review";

export const pickCategory = <C>(options: {
  readonly categories: readonly C[];
  readonly picked: C | null;
}): C | null =>
  options.picked === null && options.categories.length === 1
    ? (options.categories[0] ?? null)
    : options.picked;

const codeMessage = (options: {
  readonly code: string;
  readonly control: FieldControl | undefined;
  readonly values: readonly string[];
}): FieldError => {
  const { code, control, values } = options;

  switch (code) {
    case "required": {
      return REQUIRED_ERROR;
    }

    case "max_length": {
      const value = pyStrip(values.at(-1) ?? "");

      return maxLengthError({
        length: pyLength(value),
        limit: control?.maxLength ?? 0,
      });
    }

    case "null_characters_not_allowed": {
      return NULL_CHARACTERS_ERROR;
    }

    case "invalid_choice": {
      const known = new Set((control?.choices ?? []).map(([value]) => value));

      const offending =
        control?.kind === "multipleChoice"
          ? values.find((value) => !known.has(value))
          : values.at(-1);

      return invalidChoiceError(offending ?? "");
    }

    case "custom_answer_required": {
      return CUSTOM_ANSWER_REQUIRED_ERROR;
    }

    default: {
      return fieldError(code, code);
    }
  }
};

export interface DynamicFieldsValidation {
  readonly cleaned: Readonly<Record<string, FieldAnswer>>;
  readonly errors: FormErrors;
}

export const validateDynamicFields = (options: {
  readonly prefix: string;
  readonly pairs: readonly FieldRequirement[];
  readonly data: FormData;
}): DynamicFieldsValidation => {
  const validation = validateFieldAnswers(options);
  const { controls } = resolveFieldControls(options);
  const byKey = new Map(controls.map((control) => [control.key, control]));

  const errors = Object.fromEntries(
    Object.entries(validation.errors).map(([key, codes]) => [
      key,
      codes.map((code) =>
        codeMessage({
          code,
          control: byKey.get(key),
          values: options.data[key] ?? [],
        })
      ),
    ])
  );

  return { cleaned: validation.cleaned, errors };
};

const collect = <A>(
  errors: Map<string, readonly FieldError[]>,
  key: string,
  result: Result.Result<A, readonly FieldError[]>
): A | undefined => {
  if (Result.isFailure(result)) {
    errors.set(key, result.failure);

    return undefined;
  }

  return result.success;
};

const truthyAnswers = (
  answers: Readonly<Record<string, FieldAnswer>>
): Readonly<Record<string, FieldAnswer>> =>
  Object.fromEntries(
    Object.entries(answers).filter(([, value]) => isTruthyAnswer(value))
  );

export interface PersonalCleaned {
  readonly answers: Readonly<Record<string, FieldAnswer>>;
  readonly contactEmail: string;
}

export const validatePersonalStep = (options: {
  readonly fields: readonly FieldRequirement[];
  readonly data: FormData;
}): Result.Result<PersonalCleaned, FormErrors> => {
  const dynamic = validateDynamicFields({
    data: options.data,
    pairs: options.fields,
    prefix: "personal",
  });

  const errors = new Map<string, readonly FieldError[]>(
    Object.entries(dynamic.errors)
  );

  const contactEmail = collect(
    errors,
    "contact_email",
    cleanEmail(lastPosted(options.data, "contact_email"))
  );

  if (errors.size > 0 || contactEmail === undefined) {
    return Result.fail(Object.fromEntries(errors));
  }

  const folded = foldCustomAnswers({
    cleaned: dynamic.cleaned,
    fields: options.fields.map((pair) => pair.field),
    prefix: "personal",
  });

  return Result.succeed({ answers: truthyAnswers(folded), contactEmail });
};

export interface DetailsCategory {
  readonly durations: readonly string[];
  readonly maxParticipantsLimit: number;
  readonly minParticipantsLimit: number;
}

export interface DetailsCleaned {
  readonly answers: Readonly<Record<string, FieldAnswer>>;
  readonly description: string;
  readonly duration: string;
  readonly facilitatorName: string;
  readonly minAge: number;
  readonly participantsLimit: number;
  readonly title: string;
}

export const participantsPlaceholder = (
  category: DetailsCategory | null
): string | null => {
  const min = category?.minParticipantsLimit ?? 0;
  const max = category?.maxParticipantsLimit ?? 0;

  if (max) {
    return `${String(min)}–${String(max)}`;
  }

  return min ? `${String(min)}+` : null;
};

export const durationOptions = (
  category: DetailsCategory | null
): readonly (readonly [string, string])[] =>
  durationChoices(category?.durations ?? []);

export const soleDuration = (
  category: DetailsCategory | null
): readonly [string, string] | null => {
  const choices = durationOptions(category);

  return choices.length === 1 ? (choices[0] ?? null) : null;
};

export const validateDetailsStep = (options: {
  readonly category: DetailsCategory | null;
  readonly requirements: readonly FieldRequirement[];
  readonly data: FormData;
}): Result.Result<DetailsCleaned, FormErrors> => {
  const { category, data } = options;
  const errors = new Map<string, readonly FieldError[]>();
  const minLimit = category?.minParticipantsLimit ?? 0;
  const maxLimit = category?.maxParticipantsLimit ?? 0;

  const title = collect(
    errors,
    "title",
    cleanChar({
      maxLength: TITLE_MAX_LENGTH,
      raw: lastPosted(data, "title"),
      required: true,
    })
  );

  const description = collect(
    errors,
    "description",
    cleanChar({
      maxLength: null,
      raw: lastPosted(data, "description"),
      required: true,
    })
  );

  const participantsLimit = collect(
    errors,
    "participants_limit",
    cleanInteger({
      extraMaxValue: MAX_STORED_PARTICIPANTS_LIMIT,
      maxValue: maxLimit || null,
      minValue: minLimit,
      raw: lastPosted(data, "participants_limit"),
      required: Boolean(minLimit),
    })
  );

  const minAge = collect(
    errors,
    "min_age",
    cleanInteger({
      extraMaxValue: null,
      maxValue: MIN_AGE_MAX,
      minValue: 0,
      raw: lastPosted(data, "min_age"),
      required: false,
    })
  );

  const facilitatorName = collect(
    errors,
    FACILITATOR_NAME_FIELD,
    cleanChar({
      maxLength: TITLE_MAX_LENGTH,
      raw: lastPosted(data, FACILITATOR_NAME_FIELD),
      required: true,
    })
  );

  const choices = durationOptions(category);

  const duration =
    choices.length === 0
      ? ""
      : collect(
          errors,
          "duration",
          cleanChoice({
            choices: ["", ...choices.map(([value]) => value)],
            raw: lastPosted(data, "duration"),
            required: true,
          })
        );

  const dynamic = validateDynamicFields({
    data,
    pairs: options.requirements,
    prefix: "session",
  });

  for (const [key, fieldErrors] of Object.entries(dynamic.errors)) {
    errors.set(key, fieldErrors);
  }

  if (
    errors.size > 0 ||
    title === undefined ||
    description === undefined ||
    participantsLimit === undefined ||
    minAge === undefined ||
    facilitatorName === undefined ||
    duration === undefined
  ) {
    return Result.fail(Object.fromEntries(errors));
  }

  const folded = foldCustomAnswers({
    cleaned: dynamic.cleaned,
    fields: options.requirements.map((pair) => pair.field),
    prefix: "session",
  });

  return Result.succeed({
    answers: truthyAnswers(folded),
    description,
    duration,
    facilitatorName,
    minAge: minAge ?? 0,
    participantsLimit: participantsLimit ?? 0,
    title,
  });
};

export const accountAnswersEverything = (options: {
  readonly email: string;
  readonly answers: Readonly<Record<string, string>>;
  readonly fields: readonly FieldRequirement[];
}): boolean => {
  if (
    options.email === "" ||
    Object.keys(options.answers).length < options.fields.length
  ) {
    return false;
  }

  const data: FormData = {
    ...Object.fromEntries(
      Object.entries(options.answers).map(
        ([key, value]): readonly [string, readonly string[]] => [key, [value]]
      )
    ),
    contact_email: [options.email],
  };

  return Result.isSuccess(
    validatePersonalStep({ data, fields: options.fields })
  );
};

export const accountPersonalAnswers = (options: {
  readonly discordUsername: string;
  readonly fields: readonly OrganizerField[];
}): Readonly<Record<string, string>> =>
  Object.fromEntries(
    options.discordUsername === ""
      ? []
      : options.fields
          .filter((field) => field.fieldType === "discord")
          .map((field) => [`personal_${field.slug}`, options.discordUsername])
  );
