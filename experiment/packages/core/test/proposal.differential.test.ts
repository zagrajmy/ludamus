import { describe, expect, it } from "@effect/vitest";
import { Result, Schema } from "effect";

import {
  FieldAnswer,
  FieldRequirement,
  MAX_DURATION_HOURS,
  MAX_DURATION_MINUTES,
  OrganizerField,
  answeredValue,
  buildDuration,
  carriedAnswers,
  durationChoices,
  durationFromParts,
  foldCustomAnswers,
  formatDuration,
  mergeCustom,
  normalizeDuration,
  parseDuration,
  parseDurationPart,
  resolveFieldControls,
  splitStored,
  stepperParts,
  unfoldCustomAnswers,
  uniqueSlug,
  validateFieldAnswers,
} from "../src/proposal/index.js";
import type {
  DurationDigitError,
  InvalidDurationError,
} from "../src/proposal/index.js";
import carriedCases from "./fixtures/differential/carried_answers.json" with { type: "json" };
import durationCases from "./fixtures/differential/durations.json" with { type: "json" };
import answerCases from "./fixtures/differential/field_answers.json" with { type: "json" };
import requirementCases from "./fixtures/differential/field_requirements.json" with { type: "json" };
import validationCases from "./fixtures/differential/field_validation.json" with { type: "json" };
import slugCases from "./fixtures/differential/unique_slug.json" with { type: "json" };
import { replay } from "./support/differential.js";
import type { Json } from "./support/differential.js";

const outcomeJson = <A extends Json>(
  outcome: Result.Result<A, InvalidDurationError | DurationDigitError>
): Json => {
  if (Result.isSuccess(outcome)) {
    return { ok: outcome.success };
  }

  return {
    error:
      outcome.failure._tag === "InvalidDurationError"
        ? "InvalidDurationError"
        : "ValueError",
  };
};

const Answers = Schema.Record(Schema.String, FieldAnswer);

describe("differential: pacts.durations", () => {
  it("every duration helper answers like Python", () => {
    const mismatches = replay({
      cases: durationCases.cases,
      input: Schema.Struct({
        durations: Schema.Array(Schema.String),
        hours: Schema.Int,
        hoursPart: Schema.String,
        minutes: Schema.Int,
        minutesPart: Schema.String,
        text: Schema.NullOr(Schema.String),
      }),
      run: (input) => ({
        buildDuration: buildDuration(input),
        durationChoices: durationChoices(input.durations),
        durationFromParts: outcomeJson(
          durationFromParts({
            hours: input.hoursPart,
            minutes: input.minutesPart,
          })
        ),
        formatDuration: formatDuration(input.text),
        hoursPart: outcomeJson(
          parseDurationPart({
            maximum: MAX_DURATION_HOURS,
            raw: input.hoursPart,
          })
        ),
        minutesPart: outcomeJson(
          parseDurationPart({
            maximum: MAX_DURATION_MINUTES,
            raw: input.minutesPart,
          })
        ),
        normalizeDuration: normalizeDuration(input.text ?? ""),
        parseDuration: parseDuration(input.text),
        stepperParts: stepperParts(input.text ?? ""),
      }),
    });

    expect(durationCases.cases.length).toBeGreaterThan(400);
    expect(mismatches.slice(0, 3)).toEqual([]);
  });
});

describe("differential: dynamic fields", () => {
  it("build_dynamic_fields resolves the same controls per category", () => {
    const mismatches = replay({
      cases: requirementCases.cases,
      input: Schema.Struct({
        pairs: Schema.Array(FieldRequirement),
        prefix: Schema.String,
      }),
      run: resolveFieldControls,
    });

    expect(requirementCases.cases.length).toBeGreaterThan(250);
    expect(mismatches.slice(0, 3)).toEqual([]);
  });

  it("dynamic_fields_form validates and cleans answers like Django", () => {
    const mismatches = replay({
      cases: validationCases.cases,
      input: Schema.Struct({
        data: Schema.Record(Schema.String, Schema.Array(Schema.String)),
        pairs: Schema.Array(FieldRequirement),
        prefix: Schema.String,
      }),
      run: (input) => {
        const validation = validateFieldAnswers(input);

        return {
          ...validation,
          answered: validation.valid
            ? Object.fromEntries(
                input.pairs.map(({ field }) => [
                  field.slug,
                  answeredValue({
                    cleaned: validation.cleaned,
                    field,
                    prefix: input.prefix,
                  }),
                ])
              )
            : null,
        };
      },
    });

    expect(validationCases.cases.length).toBeGreaterThan(350);
    expect(mismatches.slice(0, 3)).toEqual([]);
  });

  it("merge_custom, split_stored, fold and unfold shape answers alike", () => {
    const mismatches = replay({
      cases: answerCases.cases,
      input: Schema.Struct({
        answers: Answers,
        chosen: Schema.NullOr(FieldAnswer),
        custom: Schema.String,
        fields: Schema.Array(OrganizerField),
        isMultiple: Schema.Boolean,
        known: Schema.Array(Schema.String),
        prefix: Schema.String,
      }),
      run: (input) => ({
        fold: foldCustomAnswers({
          cleaned: input.answers,
          fields: input.fields,
          prefix: input.prefix,
        }),
        mergeCustom: mergeCustom(input),
        splitStored: splitStored({ ...input, stored: input.chosen }),
        unfold: unfoldCustomAnswers({
          fields: input.fields,
          prefix: input.prefix,
          stored: input.answers,
        }),
      }),
    });

    expect(answerCases.cases.length).toBeGreaterThan(250);
    expect(mismatches.slice(0, 3)).toEqual([]);
  });
});

describe("differential: proposal rules and slugs", () => {
  it("carried_answers lends the same answers", () => {
    const Map = Schema.Record(Schema.String, Schema.String);

    const mismatches = replay({
      cases: carriedCases.cases,
      input: Schema.Struct({
        presented: Schema.Boolean,
        private: Map,
        public: Map,
      }),
      run: carriedAnswers,
    });

    expect(carriedCases.cases.length).toBeGreaterThan(40);
    expect(mismatches.slice(0, 3)).toEqual([]);
  });

  it("unique_slug lands on the same slug for the same collisions", () => {
    const mismatches = replay({
      cases: slugCases.cases,
      input: Schema.Struct({
        base: Schema.String,
        default: Schema.String,
        suffixes: Schema.Array(Schema.String),
        taken: Schema.Array(Schema.String),
      }),
      run: (input) => {
        const suffixes = input.suffixes.values();

        return uniqueSlug({
          base: input.base,
          exists: (slug) => input.taken.includes(slug),
          fallback: input.default,
          nextSuffix: () => suffixes.next().value ?? "",
        });
      },
    });

    expect(slugCases.cases.length).toBeGreaterThan(250);
    expect(mismatches.slice(0, 3)).toEqual([]);
  });
});
